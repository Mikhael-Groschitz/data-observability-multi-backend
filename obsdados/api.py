"""API de leitura: estado dos datasets, histórico, incidentes abertos, saúde do serviço."""

import html
import os
from datetime import datetime
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from obsdados.armazenamento import consultar_historico
from obsdados.contrato import ContratoDataset, ContratoInvalido, carregar_contrato
from obsdados.db import conectar_leitura
from obsdados.incidente import Incidente, consultar_incidentes_abertos, severidade_mais_grave
from obsdados.nucleo import ResultadoMetrica


class Saude(BaseModel):
    servico: str
    store: str
    ultima_coleta: datetime | None


class EstadoDataset(BaseModel):
    dataset: str
    backend: str
    incidentes_abertos: int
    pior_severidade: str | None
    ultima_coleta: datetime | None


class MetricaHistorico(BaseModel):
    tipo_metrica: str
    coluna: str | None
    status: str
    valor: float | None
    valor_texto: str | None
    coletado_em: datetime


class IncidenteResumo(BaseModel):
    dataset: str
    regra: str
    coluna: str | None
    severidade: str
    status: str
    valor_observado: str
    valor_esperado: str
    desvio: str
    justificativa: str
    detectado_em: datetime
    resolvido_em: datetime | None


def _store_path() -> str:
    caminho = os.environ.get("OBSDADOS_METRIC_STORE_PATH")
    if not caminho:
        raise HTTPException(status_code=503, detail="OBSDADOS_METRIC_STORE_PATH não configurado")
    return caminho


def _contratos_dir() -> Path:
    return Path(os.environ.get("OBSDADOS_CONTRATOS_DIR", "contratos"))


def _listar_contratos() -> list[ContratoDataset]:
    diretorio = _contratos_dir()
    if not diretorio.is_dir():
        return []
    contratos = []
    for caminho in sorted(diretorio.glob("*.yaml")):
        try:
            contratos.append(carregar_contrato(str(caminho)))
        except ContratoInvalido:
            continue
    return contratos


def _conectar_leitura_ou_503() -> duckdb.DuckDBPyConnection:
    try:
        return conectar_leitura(_store_path(), tentativas=2, espera_base_segundos=0.05)
    except duckdb.Error as erro:
        raise HTTPException(status_code=503, detail=f"metric store indisponível: {erro}") from erro


def _incidente_para_resumo(incidente: Incidente) -> IncidenteResumo:
    return IncidenteResumo(
        dataset=incidente.dataset,
        regra=incidente.regra.value,
        coluna=incidente.coluna,
        severidade=incidente.severidade.value,
        status=incidente.status.value,
        valor_observado=incidente.valor_observado,
        valor_esperado=incidente.valor_esperado,
        desvio=incidente.desvio,
        justificativa=incidente.justificativa,
        detectado_em=incidente.detectado_em,
        resolvido_em=incidente.resolvido_em,
    )


def montar_app() -> FastAPI:
    app = FastAPI(title="obsdados")

    @app.get("/health")
    def health() -> Saude:
        try:
            con = conectar_leitura(_store_path(), tentativas=1)
        except (HTTPException, duckdb.Error):
            return Saude(servico="ok", store="indisponivel", ultima_coleta=None)
        try:
            linha = con.execute(
                "SELECT MAX(coletado_em) FROM observabilidade.historico_metrica"
            ).fetchone()
        finally:
            con.close()
        ultima = linha[0] if linha else None
        return Saude(servico="ok", store="ok", ultima_coleta=ultima)

    @app.get("/datasets")
    def listar_datasets() -> list[EstadoDataset]:
        con = _conectar_leitura_ou_503()
        try:
            resultado = []
            for contrato in _listar_contratos():
                abertos = consultar_incidentes_abertos(con, contrato.dataset)
                pior = None
                if abertos:
                    pior = severidade_mais_grave([i.severidade for i in abertos]).value
                historico = consultar_historico(con, contrato.dataset, limite=1)
                ultima = historico[0].coletado_em if historico else None
                resultado.append(
                    EstadoDataset(
                        dataset=contrato.dataset,
                        backend=contrato.conexao.backend,
                        incidentes_abertos=len(abertos),
                        pior_severidade=pior,
                        ultima_coleta=ultima,
                    )
                )
            return resultado
        finally:
            con.close()

    @app.get("/datasets/{dataset}/historico")
    def historico_dataset(dataset: str, limite: int = 50) -> list[MetricaHistorico]:
        con = _conectar_leitura_ou_503()
        try:
            historico = consultar_historico(con, dataset, limite=limite)
        finally:
            con.close()
        return [
            MetricaHistorico(
                tipo_metrica=r.tipo_metrica.value,
                coluna=r.coluna,
                status=r.status.value,
                valor=r.valor,
                valor_texto=r.valor_texto,
                coletado_em=r.coletado_em,
            )
            for r in historico
        ]

    @app.get("/incidentes")
    def incidentes(dataset: str | None = None) -> list[IncidenteResumo]:
        con = _conectar_leitura_ou_503()
        try:
            datasets = [dataset] if dataset else [c.dataset for c in _listar_contratos()]
            resultado: list[IncidenteResumo] = []
            for ds in datasets:
                resultado.extend(
                    _incidente_para_resumo(i) for i in consultar_incidentes_abertos(con, ds)
                )
            return resultado
        finally:
            con.close()

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        con = _conectar_leitura_ou_503()
        try:
            datasets = listar_datasets()
            historicos = {
                d.dataset: consultar_historico(con, d.dataset, limite=10) for d in datasets
            }
        finally:
            con.close()
        return _renderizar_pagina(datasets, historicos)

    return app


def _formatar_valor(resultado: ResultadoMetrica) -> str:
    if resultado.valor_texto is not None:
        return resultado.valor_texto
    return "" if resultado.valor is None else str(resultado.valor)


def _linha_dataset(dataset: EstadoDataset) -> str:
    ultima = (
        dataset.ultima_coleta.isoformat(sep=" ", timespec="seconds")
        if dataset.ultima_coleta
        else "-"
    )
    celulas = [
        dataset.dataset,
        dataset.backend,
        str(dataset.incidentes_abertos),
        dataset.pior_severidade or "-",
        ultima,
    ]
    linha = "".join(f"<td>{html.escape(c)}</td>" for c in celulas)
    return f"<tr>{linha}</tr>"


def _linha_historico(resultado: ResultadoMetrica) -> str:
    celulas = [
        resultado.coletado_em.isoformat(sep=" ", timespec="seconds"),
        resultado.tipo_metrica.value,
        resultado.status.value,
        _formatar_valor(resultado),
    ]
    linha = "".join(f"<td>{html.escape(c)}</td>" for c in celulas)
    return f"<tr>{linha}</tr>"


def _renderizar_pagina(
    datasets: list[EstadoDataset], historicos: dict[str, list[ResultadoMetrica]]
) -> str:
    linhas_datasets = "".join(_linha_dataset(d) for d in datasets)
    blocos_historico = ""
    for dataset, historico in historicos.items():
        linhas = "".join(_linha_historico(r) for r in historico)
        blocos_historico += (
            f"<h2>{html.escape(dataset)}</h2>"
            "<table><tr><th>coletado_em</th><th>métrica</th><th>status</th><th>valor</th></tr>"
            f"{linhas}</table>"
        )

    return f"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>obsdados</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
table {{ border-collapse: collapse; margin-bottom: 1.5rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.8rem; text-align: left; }}
th {{ background: #f0f0f0; }}
</style>
</head>
<body>
<h1>obsdados</h1>
<h2>Datasets</h2>
<table>
<tr>
<th>dataset</th><th>backend</th><th>incidentes abertos</th>
<th>pior severidade</th><th>última coleta</th>
</tr>
{linhas_datasets}
</table>
{blocos_historico}
</body>
</html>"""


app = montar_app()

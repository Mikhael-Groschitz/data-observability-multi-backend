"""Testa a API de leitura via TestClient — não sobe servidor de verdade, mas é a mesma app."""

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from obsdados.api import montar_app
from obsdados.armazenamento import gravar_resultado_metrica
from obsdados.avaliador import avaliar_dataset
from obsdados.contrato import ConexaoContrato, ContratoDataset, RegraFrescor
from obsdados.db import conectar_escrita
from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoAmostragem, TipoMetrica

_DATASET = "demo.pedidos"


def _contrato(origem: str) -> ContratoDataset:
    return ContratoDataset(
        dataset=_DATASET,
        conexao=ConexaoContrato(backend="duckdb", db_origem=origem),
        tabela="pedidos",
        frescor=RegraFrescor(coluna="criado_em", sla_horas=24),
    )


def _resultado_frescor(valor: float) -> ResultadoMetrica:
    return ResultadoMetrica(
        dataset=_DATASET,
        tipo_metrica=TipoMetrica.FRESCOR,
        dimensao=None,
        coluna="criado_em",
        status=StatusResultadoMetrica.OK,
        valor=valor,
        tipo_amostragem=TipoAmostragem.FULL_SCAN,
        backend="duckdb",
        linhas_buscadas=1,
        duracao_segundos=0.001,
        coletado_em=datetime.now(),
    )


@pytest.fixture
def ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Prepara diretório de contratos + metric store e aponta as variáveis de ambiente da API."""
    contratos_dir = tmp_path / "contratos"
    contratos_dir.mkdir()
    origem = str(tmp_path / "origem.duckdb")
    (contratos_dir / "demo.yaml").write_text(
        f"""
dataset: {_DATASET}
conexao:
  backend: duckdb
  db_origem: {origem}
tabela: pedidos
frescor:
  coluna: criado_em
  sla_horas: 24
""",
        encoding="utf-8",
    )
    store = str(tmp_path / "metricas.duckdb")
    monkeypatch.setenv("OBSDADOS_METRIC_STORE_PATH", store)
    monkeypatch.setenv("OBSDADOS_CONTRATOS_DIR", str(contratos_dir))
    return store, origem


def _coletar_e_avaliar(store: str, origem: str, valor_frescor: float) -> None:
    con = conectar_escrita(store)
    gravar_resultado_metrica(con, _resultado_frescor(valor_frescor))
    avaliar_dataset(_contrato(origem), con)
    con.execute("CHECKPOINT")
    con.close()


def test_health_sem_store_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OBSDADOS_METRIC_STORE_PATH", raising=False)
    client = TestClient(montar_app())

    resposta = client.get("/health")

    assert resposta.status_code == 200
    assert resposta.json()["servico"] == "ok"
    assert resposta.json()["store"] == "indisponivel"


def test_health_com_store_e_coleta(ambiente: tuple[str, str]) -> None:
    store, origem = ambiente
    _coletar_e_avaliar(store, origem, 3600.0)
    client = TestClient(montar_app())

    resposta = client.get("/health")

    assert resposta.json()["servico"] == "ok"
    assert resposta.json()["store"] == "ok"
    assert resposta.json()["ultima_coleta"] is not None


def test_listar_datasets(ambiente: tuple[str, str]) -> None:
    store, origem = ambiente
    _coletar_e_avaliar(store, origem, 3600.0)
    client = TestClient(montar_app())

    resposta = client.get("/datasets")

    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["dataset"] == _DATASET
    assert corpo[0]["incidentes_abertos"] == 0


def test_historico_dataset(ambiente: tuple[str, str]) -> None:
    store, origem = ambiente
    _coletar_e_avaliar(store, origem, 3600.0)
    client = TestClient(montar_app())

    resposta = client.get(f"/datasets/{_DATASET}/historico")

    corpo = resposta.json()
    assert len(corpo) == 1
    assert corpo[0]["tipo_metrica"] == "frescor"


def test_incidente_aparece_na_api_e_some_quando_normaliza(ambiente: tuple[str, str]) -> None:
    """O roteiro de validação da fase: derruba o dado, vê o incidente, normaliza, some."""
    store, origem = ambiente
    client = TestClient(montar_app())

    _coletar_e_avaliar(store, origem, 30 * 3600.0)  # atrasado: dispara incidente
    resposta = client.get("/incidentes")
    assert len(resposta.json()) == 1
    assert resposta.json()[0]["regra"] == "frescor"
    assert client.get("/datasets").json()[0]["incidentes_abertos"] == 1

    _coletar_e_avaliar(store, origem, 3600.0)  # normaliza
    resposta_depois = client.get("/incidentes")
    assert resposta_depois.json() == []
    assert client.get("/datasets").json()[0]["incidentes_abertos"] == 0


def test_pagina_html_lista_dataset_e_historico(ambiente: tuple[str, str]) -> None:
    store, origem = ambiente
    _coletar_e_avaliar(store, origem, 3600.0)
    client = TestClient(montar_app())

    resposta = client.get("/")

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    assert _DATASET in resposta.text
    assert "frescor" in resposta.text

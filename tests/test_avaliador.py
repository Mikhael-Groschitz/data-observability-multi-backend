"""Testa o avaliador com anomalias sintéticas: volume, schema, frescor e nulos.

Cada teste injeta a anomalia que o roteiro de validação do projeto pede
(volume pela metade, coluna removida, carga atrasada) e confere o incidente
com a justificativa — não só que "algo disparou".
"""

from datetime import datetime, timedelta
from typing import Any

from obsdados.armazenamento import gravar_resultado_metrica
from obsdados.avaliador import avaliar_dataset
from obsdados.contrato import (
    ConexaoContrato,
    ContratoDataset,
    RegraFrescor,
    RegraNulos,
    RegraSchema,
    RegraVolume,
)
from obsdados.db import conectar_escrita
from obsdados.incidente import RegraIncidente, SeveridadeRegra, consultar_incidentes_abertos
from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoAmostragem, TipoMetrica


def _contrato(**overrides: Any) -> ContratoDataset:
    campos: dict[str, Any] = {
        "dataset": "vendas.pedidos",
        "conexao": ConexaoContrato(backend="duckdb", db_origem="origem.duckdb"),
        "tabela": "vendas.pedidos",
    }
    campos.update(overrides)
    return ContratoDataset(**campos)


def _metrica(**overrides: Any) -> ResultadoMetrica:
    campos: dict[str, Any] = {
        "dataset": "vendas.pedidos",
        "tipo_metrica": TipoMetrica.CONTAGEM_LINHAS,
        "dimensao": None,
        "coluna": None,
        "status": StatusResultadoMetrica.OK,
        "valor": None,
        "valor_texto": None,
        "tipo_amostragem": TipoAmostragem.FULL_SCAN,
        "backend": "duckdb",
        "linhas_buscadas": 1,
        "duracao_segundos": 0.001,
        "coletado_em": datetime.now(),
        "parametros": {},
    }
    campos.update(overrides)
    return ResultadoMetrica(**campos)


# --- volume: injeção de "queda pela metade" -------------------------------------------------


def test_volume_incidente_quando_cai_pela_metade() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(
        volume=RegraVolume(severidade=SeveridadeRegra.CRITICO, minimo_observacoes_baseline=5)
    )
    primeira_segunda = datetime(2026, 1, 5)
    for semana in range(6):
        gravar_resultado_metrica(
            con,
            _metrica(valor=1000.0 + semana, coletado_em=primeira_segunda + timedelta(weeks=semana)),
        )
    gravar_resultado_metrica(
        con, _metrica(valor=500.0, coletado_em=primeira_segunda + timedelta(weeks=6))
    )

    resultado = avaliar_dataset(contrato, con)

    assert len(resultado.abertos) == 1
    incidente = resultado.abertos[0]
    assert incidente.regra == RegraIncidente.VOLUME
    assert incidente.severidade == SeveridadeRegra.CRITICO
    assert "500" in incidente.valor_observado
    assert "vendas.pedidos" in incidente.justificativa


def test_volume_partida_fria_nao_dispara_incidente() -> None:
    """Menos observações que o mínimo configurado: sem baseline, sem incidente estatístico."""
    con = conectar_escrita(":memory:")
    contrato = _contrato(volume=RegraVolume(minimo_observacoes_baseline=5))
    primeira_segunda = datetime(2026, 1, 5)
    for semana in range(2):
        gravar_resultado_metrica(
            con, _metrica(valor=1000.0, coletado_em=primeira_segunda + timedelta(weeks=semana))
        )
    gravar_resultado_metrica(
        con, _metrica(valor=10.0, coletado_em=primeira_segunda + timedelta(weeks=2))
    )

    resultado = avaliar_dataset(contrato, con)

    assert resultado.abertos == []
    assert resultado.resolvidos == []
    assert consultar_incidentes_abertos(con, contrato.dataset) == []


def test_volume_nao_duplica_incidente_e_resolve_quando_normaliza() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(volume=RegraVolume(minimo_observacoes_baseline=5))
    primeira_segunda = datetime(2026, 1, 5)
    for semana in range(6):
        gravar_resultado_metrica(
            con, _metrica(valor=1000.0, coletado_em=primeira_segunda + timedelta(weeks=semana))
        )
    gravar_resultado_metrica(
        con, _metrica(valor=500.0, coletado_em=primeira_segunda + timedelta(weeks=6))
    )

    primeira_rodada = avaliar_dataset(contrato, con)
    assert len(primeira_rodada.abertos) == 1
    assert primeira_rodada.resolvidos == []

    segunda_rodada = avaliar_dataset(contrato, con)
    assert segunda_rodada.abertos == []
    assert segunda_rodada.resolvidos == []
    assert len(consultar_incidentes_abertos(con, contrato.dataset)) == 1

    gravar_resultado_metrica(
        con, _metrica(valor=1000.0, coletado_em=primeira_segunda + timedelta(weeks=7))
    )
    terceira_rodada = avaliar_dataset(contrato, con)

    assert terceira_rodada.abertos == []
    assert len(terceira_rodada.resolvidos) == 1
    assert terceira_rodada.resolvidos[0].regra == RegraIncidente.VOLUME
    assert consultar_incidentes_abertos(con, contrato.dataset) == []


# --- schema: injeção de "coluna removida" ----------------------------------------------------


def test_schema_incidente_quebradora_quando_coluna_removida() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(
        schema_=RegraSchema(
            severidade_quebradora=SeveridadeRegra.CRITICO, severidade_aditiva=SeveridadeRegra.AVISO
        )
    )
    colunas_completas = [
        {"nome": "id", "tipo": "INTEGER", "aceita_nulo": False},
        {"nome": "valor", "tipo": "DOUBLE", "aceita_nulo": True},
        {"nome": "regiao", "tipo": "VARCHAR", "aceita_nulo": True},
    ]
    colunas_sem_regiao = [c for c in colunas_completas if c["nome"] != "regiao"]

    gravar_resultado_metrica(
        con,
        _metrica(
            tipo_metrica=TipoMetrica.SCHEMA_HASH,
            valor_texto="hashA",
            coletado_em=datetime(2026, 1, 1),
            parametros={"colunas": colunas_completas},
        ),
    )
    gravar_resultado_metrica(
        con,
        _metrica(
            tipo_metrica=TipoMetrica.SCHEMA_HASH,
            valor_texto="hashB",
            coletado_em=datetime(2026, 1, 2),
            parametros={"colunas": colunas_sem_regiao},
        ),
    )

    resultado = avaliar_dataset(contrato, con)

    assert len(resultado.abertos) == 1
    assert resultado.abertos[0].regra == RegraIncidente.SCHEMA
    assert resultado.abertos[0].severidade == SeveridadeRegra.CRITICO
    assert "regiao" in resultado.abertos[0].justificativa


def test_schema_incidente_aditiva_quando_coluna_nova() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(schema_=RegraSchema())
    colunas_antes = [{"nome": "id", "tipo": "INTEGER", "aceita_nulo": False}]
    campo_novo = {"nome": "novo_campo", "tipo": "VARCHAR", "aceita_nulo": True}
    colunas_depois = [*colunas_antes, campo_novo]

    gravar_resultado_metrica(
        con,
        _metrica(
            tipo_metrica=TipoMetrica.SCHEMA_HASH,
            valor_texto="hashA",
            coletado_em=datetime(2026, 1, 1),
            parametros={"colunas": colunas_antes},
        ),
    )
    gravar_resultado_metrica(
        con,
        _metrica(
            tipo_metrica=TipoMetrica.SCHEMA_HASH,
            valor_texto="hashB",
            coletado_em=datetime(2026, 1, 2),
            parametros={"colunas": colunas_depois},
        ),
    )

    resultado = avaliar_dataset(contrato, con)

    assert len(resultado.abertos) == 1
    assert resultado.abertos[0].severidade == SeveridadeRegra.AVISO
    assert "novo_campo" in resultado.abertos[0].justificativa


def test_schema_sem_mudanca_nao_gera_incidente() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(schema_=RegraSchema())
    colunas = [{"nome": "id", "tipo": "INTEGER", "aceita_nulo": False}]
    for dia in (1, 2):
        gravar_resultado_metrica(
            con,
            _metrica(
                tipo_metrica=TipoMetrica.SCHEMA_HASH,
                valor_texto="hash_estavel",
                coletado_em=datetime(2026, 1, dia),
                parametros={"colunas": colunas},
            ),
        )

    resultado = avaliar_dataset(contrato, con)

    assert resultado.abertos == []
    assert resultado.resolvidos == []


# --- frescor: injeção de "carga atrasada" ----------------------------------------------------


def test_frescor_incidente_quando_atrasado() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(frescor=RegraFrescor(coluna="criado_em", sla_horas=24))
    gravar_resultado_metrica(
        con,
        _metrica(
            tipo_metrica=TipoMetrica.FRESCOR, coluna="criado_em", valor=30 * 3600.0
        ),
    )

    resultado = avaliar_dataset(contrato, con)

    assert len(resultado.abertos) == 1
    assert resultado.abertos[0].regra == RegraIncidente.FRESCOR
    assert "30" in resultado.abertos[0].valor_observado


def test_frescor_dentro_do_sla_nao_gera_incidente() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(frescor=RegraFrescor(coluna="criado_em", sla_horas=24))
    gravar_resultado_metrica(
        con, _metrica(tipo_metrica=TipoMetrica.FRESCOR, coluna="criado_em", valor=3600.0)
    )

    resultado = avaliar_dataset(contrato, con)

    assert resultado.abertos == []


# --- nulos ------------------------------------------------------------------------------------


def test_nulos_incidente_quando_acima_do_limite() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(nulos=[RegraNulos(coluna="valor", limite_taxa=0.05)])
    gravar_resultado_metrica(
        con, _metrica(tipo_metrica=TipoMetrica.TAXA_NULOS, coluna="valor", valor=0.20)
    )

    resultado = avaliar_dataset(contrato, con)

    assert len(resultado.abertos) == 1
    assert resultado.abertos[0].regra == RegraIncidente.NULOS
    assert resultado.abertos[0].coluna == "valor"


def test_nulos_dentro_do_limite_nao_gera_incidente() -> None:
    con = conectar_escrita(":memory:")
    contrato = _contrato(nulos=[RegraNulos(coluna="valor", limite_taxa=0.05)])
    gravar_resultado_metrica(
        con, _metrica(tipo_metrica=TipoMetrica.TAXA_NULOS, coluna="valor", valor=0.01)
    )

    resultado = avaliar_dataset(contrato, con)

    assert resultado.abertos == []

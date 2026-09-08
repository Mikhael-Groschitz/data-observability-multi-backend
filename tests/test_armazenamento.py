"""Testa bootstrap do schema, gravação e consulta de histórico no metric store."""

from datetime import datetime
from typing import Any

from obsdados.armazenamento import consultar_historico, gravar_resultado_metrica
from obsdados.db import conectar_escrita
from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoAmostragem, TipoMetrica


def _resultado(**sobrescritas: Any) -> ResultadoMetrica:
    campos: dict[str, Any] = {
        "dataset": "ds",
        "tipo_metrica": TipoMetrica.CONTAGEM_LINHAS,
        "dimensao": None,
        "status": StatusResultadoMetrica.OK,
        "valor": 10.0,
        "tipo_amostragem": TipoAmostragem.FULL_SCAN,
        "backend": "duckdb",
        "linhas_buscadas": 1,
        "duracao_segundos": 0.01,
        "coletado_em": datetime.now(),
    }
    campos.update(sobrescritas)
    return ResultadoMetrica(**campos)


def test_gravar_e_consultar_historico() -> None:
    con = conectar_escrita(":memory:")

    gravar_resultado_metrica(con, _resultado(valor=10.0))
    gravar_resultado_metrica(con, _resultado(valor=20.0))

    historico = consultar_historico(con, "ds")

    assert len(historico) == 2
    assert {resultado.valor for resultado in historico} == {10.0, 20.0}


def test_consultar_historico_filtra_por_dataset() -> None:
    con = conectar_escrita(":memory:")
    gravar_resultado_metrica(con, _resultado(dataset="ds_a"))
    gravar_resultado_metrica(con, _resultado(dataset="ds_b"))

    historico = consultar_historico(con, "ds_a")

    assert len(historico) == 1
    assert historico[0].dataset == "ds_a"


def test_consultar_historico_respeita_limite() -> None:
    con = conectar_escrita(":memory:")
    for _ in range(5):
        gravar_resultado_metrica(con, _resultado())

    historico = consultar_historico(con, "ds", limite=2)

    assert len(historico) == 2

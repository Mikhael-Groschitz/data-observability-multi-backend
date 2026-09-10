"""Testa bootstrap do schema, gravação e consulta de histórico no metric store."""

from datetime import datetime, timedelta
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
    base = datetime(2026, 1, 5, 10, 0)

    gravar_resultado_metrica(con, _resultado(valor=10.0, coletado_em=base))
    gravar_resultado_metrica(con, _resultado(valor=20.0, coletado_em=base + timedelta(minutes=1)))

    historico = consultar_historico(con, "ds")

    assert len(historico) == 2
    assert {resultado.valor for resultado in historico} == {10.0, 20.0}


def test_gravar_no_mesmo_minuto_e_idempotente() -> None:
    """Duas coletas no mesmo minuto viram uma linha só, com o valor mais recente."""
    con = conectar_escrita(":memory:")
    minuto = datetime(2026, 1, 5, 10, 0, 5)
    dez_segundos_depois = minuto + timedelta(seconds=10)

    gravar_resultado_metrica(con, _resultado(valor=10.0, coletado_em=minuto))
    gravar_resultado_metrica(con, _resultado(valor=99.0, coletado_em=dez_segundos_depois))

    historico = consultar_historico(con, "ds")

    assert len(historico) == 1
    assert historico[0].valor == 99.0


def test_consultar_historico_filtra_por_dataset() -> None:
    con = conectar_escrita(":memory:")
    gravar_resultado_metrica(con, _resultado(dataset="ds_a"))
    gravar_resultado_metrica(con, _resultado(dataset="ds_b"))

    historico = consultar_historico(con, "ds_a")

    assert len(historico) == 1
    assert historico[0].dataset == "ds_a"


def test_consultar_historico_respeita_limite() -> None:
    con = conectar_escrita(":memory:")
    base = datetime(2026, 1, 5, 10, 0)
    for minuto in range(5):
        gravar_resultado_metrica(con, _resultado(coletado_em=base + timedelta(minutes=minuto)))

    historico = consultar_historico(con, "ds", limite=2)

    assert len(historico) == 2


def test_consultar_historico_filtra_por_coluna() -> None:
    con = conectar_escrita(":memory:")
    gravar_resultado_metrica(con, _resultado(coluna="valor", tipo_metrica=TipoMetrica.TAXA_NULOS))
    gravar_resultado_metrica(con, _resultado(coluna="regiao", tipo_metrica=TipoMetrica.TAXA_NULOS))

    historico = consultar_historico(con, "ds", coluna="valor")

    assert len(historico) == 1
    assert historico[0].coluna == "valor"


def test_valor_texto_e_parametros_sao_preservados() -> None:
    con = conectar_escrita(":memory:")
    gravar_resultado_metrica(
        con,
        _resultado(
            tipo_metrica=TipoMetrica.SCHEMA_HASH,
            valor=None,
            valor_texto="abc123",
            parametros={"quantil": 0.95},
        ),
    )

    historico = consultar_historico(con, "ds")

    assert historico[0].valor_texto == "abc123"
    assert historico[0].parametros == {"quantil": 0.95}

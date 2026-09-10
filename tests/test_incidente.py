"""Testa persistência e ciclo de vida do incidente no metric store."""

from datetime import datetime

from obsdados.db import conectar_escrita
from obsdados.incidente import (
    Incidente,
    RegraIncidente,
    SeveridadeRegra,
    consultar_incidentes_abertos,
    gravar_incidente,
    marcar_resolvido,
    severidade_mais_grave,
)


def _incidente(**sobrescritas: object) -> Incidente:
    campos: dict[str, object] = {
        "dataset": "ds",
        "regra": RegraIncidente.VOLUME,
        "coluna": None,
        "severidade": SeveridadeRegra.ERRO,
        "valor_observado": "500",
        "valor_esperado": "1000",
        "desvio": "6.0 MADs",
        "justificativa": "queda de volume",
        "detectado_em": datetime.now(),
    }
    campos.update(sobrescritas)
    return Incidente(**campos)


def test_gravar_e_consultar_abertos() -> None:
    con = conectar_escrita(":memory:")
    gravar_incidente(con, _incidente())

    abertos = consultar_incidentes_abertos(con, "ds")

    assert len(abertos) == 1
    assert abertos[0].justificativa == "queda de volume"
    assert abertos[0].id is not None


def test_marcar_resolvido_tira_da_lista_de_abertos() -> None:
    con = conectar_escrita(":memory:")
    gravar_incidente(con, _incidente())
    (aberto,) = consultar_incidentes_abertos(con, "ds")

    assert aberto.id is not None
    marcar_resolvido(con, aberto.id, datetime.now())

    assert consultar_incidentes_abertos(con, "ds") == []


def test_consultar_abertos_filtra_por_regra_e_coluna() -> None:
    con = conectar_escrita(":memory:")
    gravar_incidente(con, _incidente(regra=RegraIncidente.VOLUME, coluna=None))
    gravar_incidente(con, _incidente(regra=RegraIncidente.NULOS, coluna="valor"))

    apenas_nulos = consultar_incidentes_abertos(con, "ds", regra=RegraIncidente.NULOS)

    assert len(apenas_nulos) == 1
    assert apenas_nulos[0].coluna == "valor"


def test_severidade_mais_grave() -> None:
    assert severidade_mais_grave([SeveridadeRegra.AVISO]) == SeveridadeRegra.AVISO
    assert (
        severidade_mais_grave([SeveridadeRegra.AVISO, SeveridadeRegra.CRITICO])
        == SeveridadeRegra.CRITICO
    )
    assert (
        severidade_mais_grave([SeveridadeRegra.ERRO, SeveridadeRegra.AVISO]) == SeveridadeRegra.ERRO
    )

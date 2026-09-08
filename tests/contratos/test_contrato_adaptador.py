"""Suíte de contrato parametrizada: todo adapter precisa respeitar push-down."""

from collections.abc import Iterator

import duckdb
import pytest

from obsdados.adaptador import Adaptador
from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.nucleo import EspecificacaoMetrica, StatusResultadoMetrica, TipoMetrica

from ._asserts import assert_respeita_limite_pushdown


@pytest.fixture(params=["duckdb"])
def adaptador_em_teste(request: pytest.FixtureRequest) -> Iterator[Adaptador]:
    if request.param == "duckdb":
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE tabela_teste AS SELECT * FROM range(500) AS t(id)")
        yield AdaptadorDuckDB(con)
        con.close()
        return
    raise ValueError(f"backend sem fixture de contrato: {request.param}")


def test_metrica_respeita_limite_de_pushdown(adaptador_em_teste: Adaptador) -> None:
    especificacao = EspecificacaoMetrica(
        dataset="ds", tabela="tabela_teste", tipo_metrica=TipoMetrica.CONTAGEM_LINHAS
    )
    resultado = adaptador_em_teste.executar_metrica(especificacao)

    assert resultado.status in (StatusResultadoMetrica.OK, StatusResultadoMetrica.NAO_SUPORTADO)
    assert_respeita_limite_pushdown(resultado)

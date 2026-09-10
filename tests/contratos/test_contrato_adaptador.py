"""Suíte de contrato parametrizada: todo adapter precisa respeitar push-down.

Cobre as quatro famílias de métrica (volume, frescor, schema, distribuição) em
todo backend registrado aqui. `SCHEMA_HASH` usa um limite maior porque conta
colunas de metadado, não linhas de dado — ver `obsdados.adaptador`.
"""

from collections.abc import Iterator
from typing import Any

import duckdb
import psycopg
import pytest

from obsdados.adaptador import Adaptador
from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.adaptadores.adaptador_postgres import AdaptadorPostgres
from obsdados.nucleo import EspecificacaoMetrica, StatusResultadoMetrica, TipoMetrica

from ._asserts import assert_respeita_limite_pushdown

_LIMITE_SCHEMA = 50


@pytest.fixture(params=["duckdb", "postgres"])
def adaptador_em_teste(request: pytest.FixtureRequest) -> Iterator[Adaptador]:
    if request.param == "duckdb":
        con = duckdb.connect(":memory:")
        con.execute(
            """
            CREATE TABLE tabela_teste AS
            SELECT i AS id, i * 1.0 AS valor, now() - to_seconds(i) AS criado_em
            FROM range(500) AS t(i)
            """
        )
        yield AdaptadorDuckDB(con)
        con.close()
        return
    if request.param == "postgres":
        con_pg: psycopg.Connection[Any] = request.getfixturevalue("conexao_postgres")
        con_pg.execute("DROP TABLE IF EXISTS tabela_teste")
        con_pg.execute("CREATE TABLE tabela_teste (id INTEGER, valor NUMERIC, criado_em TIMESTAMP)")
        con_pg.execute(
            """
            INSERT INTO tabela_teste (id, valor, criado_em)
            SELECT i, i * 1.0, now() - (i || ' seconds')::interval
            FROM generate_series(0, 499) AS t(i)
            """
        )
        con_pg.commit()
        yield AdaptadorPostgres(con_pg)
        return
    raise ValueError(f"backend sem fixture de contrato: {request.param}")


@pytest.mark.parametrize(
    ("tipo_metrica", "coluna", "limite"),
    [
        (TipoMetrica.CONTAGEM_LINHAS, None, None),
        (TipoMetrica.FRESCOR, "criado_em", None),
        (TipoMetrica.SCHEMA_HASH, None, _LIMITE_SCHEMA),
        (TipoMetrica.TAXA_NULOS, "valor", None),
    ],
)
def test_metrica_respeita_limite_de_pushdown(
    adaptador_em_teste: Adaptador, tipo_metrica: TipoMetrica, coluna: str | None, limite: int | None
) -> None:
    especificacao = EspecificacaoMetrica(
        dataset="ds", tabela="tabela_teste", tipo_metrica=tipo_metrica, coluna=coluna
    )
    resultado = adaptador_em_teste.executar_metrica(especificacao)

    status_aceitos = (
        StatusResultadoMetrica.OK,
        StatusResultadoMetrica.NAO_SUPORTADO,
        StatusResultadoMetrica.ERRO,
    )
    assert resultado.status in status_aceitos
    if limite is None:
        assert_respeita_limite_pushdown(resultado)
    else:
        assert_respeita_limite_pushdown(resultado, limite=limite)

"""Fixtures compartilhadas entre os testes."""

from dataclasses import dataclass

import duckdb
import pytest


@dataclass
class TabelaTeste:
    conexao: duckdb.DuckDBPyConnection
    nome: str
    linhas: int


@pytest.fixture
def tabela_teste_pequena() -> TabelaTeste:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE tabela_teste AS SELECT * FROM range(5) AS t(id)")
    return TabelaTeste(conexao=con, nome="tabela_teste", linhas=5)


@pytest.fixture
def tabela_teste_com_mil_linhas() -> TabelaTeste:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE tabela_grande AS SELECT * FROM range(1000) AS t(id)")
    return TabelaTeste(conexao=con, nome="tabela_grande", linhas=1000)

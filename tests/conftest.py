"""Fixtures compartilhadas entre os testes."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import duckdb
import psycopg
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


def conectar_postgres_teste() -> "psycopg.Connection[Any]":
    """Conecta ao Postgres de teste (docker-compose local), sem tocar em nenhum banco real."""
    return psycopg.connect(
        host=os.environ.get("OBSDADOS_POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("OBSDADOS_POSTGRES_PORTA", "5433")),
        dbname=os.environ.get("OBSDADOS_POSTGRES_BANCO", "obsdados_teste"),
        user=os.environ.get("OBSDADOS_POSTGRES_USUARIO", "obsdados"),
        password=os.environ.get("OBSDADOS_POSTGRES_SENHA", "obsdados_dev"),
        connect_timeout=2,
    )


@pytest.fixture(scope="session")
def _postgres_disponivel() -> bool:
    """Testa a conexão uma única vez por sessão — evita repetir o timeout de rede por teste."""
    try:
        con = conectar_postgres_teste()
    except psycopg.Error:
        return False
    con.close()
    return True


@pytest.fixture
def conexao_postgres(_postgres_disponivel: bool) -> Iterator["psycopg.Connection[Any]"]:
    """Conexão Postgres de teste; pula o teste se o banco não estiver acessível.

    Mantém a suíte portátil: numa máquina (ou CI) sem o docker-compose deste
    projeto no ar, os testes de Postgres são pulados em vez de falhar.
    """
    if not _postgres_disponivel:
        pytest.skip("Postgres de teste indisponível — suba com `docker compose up -d postgres`")
    con = conectar_postgres_teste()
    yield con
    con.close()

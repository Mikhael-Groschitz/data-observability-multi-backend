"""Conecta um adapter de origem a partir de backend + parâmetros — sem depender da CLI."""

import os
from collections.abc import Callable
from typing import Any

import duckdb
import psycopg

from obsdados.adaptador import Adaptador
from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.adaptadores.adaptador_postgres import AdaptadorPostgres

_VARIAVEIS_POSTGRES_OBRIGATORIAS = (
    "OBSDADOS_POSTGRES_HOST",
    "OBSDADOS_POSTGRES_BANCO",
    "OBSDADOS_POSTGRES_USUARIO",
)


class ConfiguracaoOrigemInvalida(RuntimeError):
    """Backend desconhecido ou faltando o que precisa para conectar."""


def conectar_postgres_env() -> "psycopg.Connection[Any]":
    faltantes = [nome for nome in _VARIAVEIS_POSTGRES_OBRIGATORIAS if not os.environ.get(nome)]
    if faltantes:
        raise ConfiguracaoOrigemInvalida(
            f"variáveis de ambiente obrigatórias ausentes: {', '.join(faltantes)}"
        )
    return psycopg.connect(
        host=os.environ["OBSDADOS_POSTGRES_HOST"],
        port=int(os.environ.get("OBSDADOS_POSTGRES_PORTA", "5432")),
        dbname=os.environ["OBSDADOS_POSTGRES_BANCO"],
        user=os.environ["OBSDADOS_POSTGRES_USUARIO"],
        password=os.environ.get("OBSDADOS_POSTGRES_SENHA", ""),
    )


def conectar_origem(backend: str, db_origem: str | None) -> tuple[Adaptador, Callable[[], None]]:
    if backend == "duckdb":
        if not db_origem:
            raise ConfiguracaoOrigemInvalida("db_origem é obrigatório para backend duckdb")
        con = duckdb.connect(db_origem, read_only=True)
        return AdaptadorDuckDB(con), con.close
    if backend == "postgres":
        con_pg = conectar_postgres_env()
        return AdaptadorPostgres(con_pg), con_pg.close
    raise ConfiguracaoOrigemInvalida(f"backend desconhecido: {backend}")

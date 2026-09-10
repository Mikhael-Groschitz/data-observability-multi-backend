"""Instrumentação que prova, em tempo de execução, que um adapter respeita push-down."""

from collections.abc import Sequence
from typing import Any

import duckdb
import psycopg


class ConexaoInstrumentadaDuckDB:
    """Envolve uma conexão DuckDB contando linhas buscadas via fetch*."""

    def __init__(self, conexao: duckdb.DuckDBPyConnection) -> None:
        self._conexao = conexao
        self.linhas_buscadas_total = 0

    def execute(
        self, sql: str, parametros: Sequence[object] | None = None
    ) -> "ConexaoInstrumentadaDuckDB":
        self._conexao.execute(sql, parametros or [])
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        linha = self._conexao.fetchone()
        if linha is not None:
            self.linhas_buscadas_total += 1
        return linha

    def fetchmany(self, tamanho: int = 1) -> list[tuple[Any, ...]]:
        linhas = self._conexao.fetchmany(tamanho)
        self.linhas_buscadas_total += len(linhas)
        return linhas

    def fetchall(self) -> list[tuple[Any, ...]]:
        linhas = self._conexao.fetchall()
        self.linhas_buscadas_total += len(linhas)
        return linhas

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._conexao, nome)


class ConexaoInstrumentadaPsycopg:
    """Envolve uma conexão psycopg contando linhas buscadas via fetch*.

    Ao contrário do DuckDB, a conexão do psycopg não tem `fetchone`/`fetchall`
    direto — `execute` devolve um cursor, e é nele que os fetch* acontecem.
    """

    def __init__(self, conexao: "psycopg.Connection[Any]") -> None:
        self._conexao = conexao
        self._cursor: psycopg.Cursor[Any] | None = None
        self.linhas_buscadas_total = 0

    def execute(
        self, sql: str, parametros: Sequence[object] | None = None
    ) -> "ConexaoInstrumentadaPsycopg":
        if self._cursor is not None:
            self._cursor.close()
        self._cursor = self._conexao.execute(sql, parametros)
        return self

    def _cursor_ativo(self) -> "psycopg.Cursor[Any]":
        if self._cursor is None:
            raise RuntimeError("execute() precisa ser chamado antes de qualquer fetch")
        return self._cursor

    def fetchone(self) -> tuple[Any, ...] | None:
        linha = self._cursor_ativo().fetchone()
        if linha is not None:
            self.linhas_buscadas_total += 1
        return linha

    def fetchall(self) -> list[tuple[Any, ...]]:
        linhas = self._cursor_ativo().fetchall()
        self.linhas_buscadas_total += len(linhas)
        return linhas

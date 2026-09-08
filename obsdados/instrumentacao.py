"""Instrumentação que prova, em tempo de execução, que um adapter respeita push-down."""

from collections.abc import Sequence
from typing import Any

import duckdb


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

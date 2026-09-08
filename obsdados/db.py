"""Conexão com o metric store DuckDB: escrita de vida curta, leitura com retry."""

import time
from collections.abc import Callable

import duckdb

from obsdados.armazenamento import gravar_resultado_metrica
from obsdados.nucleo import ResultadoMetrica

_SQL_BOOTSTRAP = """
CREATE SCHEMA IF NOT EXISTS observabilidade;

CREATE SEQUENCE IF NOT EXISTS observabilidade.seq_historico_metrica START 1;

CREATE TABLE IF NOT EXISTS observabilidade.historico_metrica (
    id                    BIGINT PRIMARY KEY
        DEFAULT nextval('observabilidade.seq_historico_metrica'),
    dataset               VARCHAR NOT NULL,
    tipo_metrica          VARCHAR NOT NULL,
    dimensao              VARCHAR,
    coletado_em           TIMESTAMP NOT NULL,
    valor                 DOUBLE,
    status                VARCHAR NOT NULL,
    tipo_amostragem       VARCHAR NOT NULL DEFAULT 'nao_aplicavel',
    motivo_nao_suportado  VARCHAR,
    mensagem_erro         VARCHAR,
    backend               VARCHAR NOT NULL,
    linhas_buscadas       INTEGER NOT NULL,
    duracao_segundos      DOUBLE NOT NULL,
    parametros_metrica    VARCHAR,
    _inserido_em          TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_historico_metrica_consulta
    ON observabilidade.historico_metrica (dataset, tipo_metrica, dimensao, coletado_em);
"""


class ErroMetricStoreOcupado(RuntimeError):
    """Levantado quando o metric store segue bloqueado pelo escritor após todas as tentativas."""


def _bootstrap(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_SQL_BOOTSTRAP)


def conectar_escrita(caminho: str) -> duckdb.DuckDBPyConnection:
    """Abre conexão read-write no metric store e garante que o schema existe."""
    con = duckdb.connect(caminho)
    _bootstrap(con)
    return con


def gravar_e_fechar(con: duckdb.DuckDBPyConnection, resultado: ResultadoMetrica) -> None:
    """Grava um resultado, faz CHECKPOINT e fecha — mantém a janela de escrita curta."""
    gravar_resultado_metrica(con, resultado)
    # sem isso, uma conexão read_only aberta depois não vê o commit (ela não faz replay de WAL)
    con.execute("CHECKPOINT")
    con.close()


def conectar_leitura(
    caminho: str,
    *,
    tentativas: int = 5,
    espera_base_segundos: float = 0.05,
    dormir: Callable[[float], None] = time.sleep,
) -> duckdb.DuckDBPyConnection:
    """Abre conexão read_only no metric store, com retry/backoff se o escritor estiver ativo."""
    ultimo_erro: duckdb.Error | None = None
    for tentativa in range(tentativas):
        try:
            return duckdb.connect(caminho, read_only=True)
        except duckdb.Error as erro:
            ultimo_erro = erro
            if tentativa < tentativas - 1:
                dormir(espera_base_segundos * (tentativa + 1))
    raise ErroMetricStoreOcupado(
        f"metric store '{caminho}' permaneceu bloqueado pelo escritor após {tentativas} tentativas"
    ) from ultimo_erro

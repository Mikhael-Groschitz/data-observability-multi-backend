"""Estado de notificação por chave de incidente: última vez enviada e quantas foram suprimidas."""

from datetime import datetime

import duckdb
from pydantic import BaseModel, ConfigDict


class EstadoNotificacao(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chave: str
    dataset: str
    regra: str
    coluna: str | None
    ultimo_evento: str
    ultima_notificacao_em: datetime
    suprimidas: int


def montar_chave(dataset: str, regra: str, coluna: str | None) -> str:
    return f"{dataset}|{regra}|{coluna or ''}"


_SQL_BUSCAR = """
SELECT chave, dataset, regra, coluna, ultimo_evento, ultima_notificacao_em, suprimidas
FROM observabilidade.notificacao WHERE chave = ?
"""

_SQL_UPSERT = """
INSERT INTO observabilidade.notificacao (
    chave, dataset, regra, coluna, ultimo_evento, ultima_notificacao_em, suprimidas
) VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (chave) DO UPDATE SET
    ultimo_evento = excluded.ultimo_evento,
    ultima_notificacao_em = excluded.ultima_notificacao_em,
    suprimidas = excluded.suprimidas
"""


def buscar_estado(con: duckdb.DuckDBPyConnection, chave: str) -> EstadoNotificacao | None:
    linha = con.execute(_SQL_BUSCAR, [chave]).fetchone()
    if linha is None:
        return None
    return EstadoNotificacao(
        chave=linha[0],
        dataset=linha[1],
        regra=linha[2],
        coluna=linha[3],
        ultimo_evento=linha[4],
        ultima_notificacao_em=linha[5],
        suprimidas=linha[6],
    )


def registrar_envio(  # noqa: PLR0913, PLR0917
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    regra: str,
    coluna: str | None,
    evento: str,
    agora: datetime,
) -> None:
    chave = montar_chave(dataset, regra, coluna)
    con.execute(_SQL_UPSERT, [chave, dataset, regra, coluna, evento, agora, 0])


def registrar_supressao(con: duckdb.DuckDBPyConnection, estado: EstadoNotificacao) -> None:
    con.execute(
        _SQL_UPSERT,
        [
            estado.chave,
            estado.dataset,
            estado.regra,
            estado.coluna,
            estado.ultimo_evento,
            estado.ultima_notificacao_em,
            estado.suprimidas + 1,
        ],
    )

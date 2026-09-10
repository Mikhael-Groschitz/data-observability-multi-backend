"""Modelo de incidente e persistência no metric store."""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final

import duckdb
from pydantic import BaseModel, ConfigDict


class SeveridadeRegra(StrEnum):
    AVISO = "aviso"
    ERRO = "erro"
    CRITICO = "critico"


_ORDEM_SEVERIDADE: Final[dict[SeveridadeRegra, int]] = {
    SeveridadeRegra.AVISO: 0,
    SeveridadeRegra.ERRO: 1,
    SeveridadeRegra.CRITICO: 2,
}


def severidade_mais_grave(severidades: Sequence[SeveridadeRegra]) -> SeveridadeRegra:
    return max(severidades, key=lambda s: _ORDEM_SEVERIDADE[s])


class RegraIncidente(StrEnum):
    FRESCOR = "frescor"
    VOLUME = "volume"
    SCHEMA = "schema"
    NULOS = "nulos"


class StatusIncidente(StrEnum):
    ABERTO = "aberto"
    RESOLVIDO = "resolvido"


class Incidente(BaseModel):
    """Um desvio detectado pelo avaliador, com o suficiente para justificar sozinho."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int | None = None
    dataset: str
    regra: RegraIncidente
    coluna: str | None = None
    severidade: SeveridadeRegra
    status: StatusIncidente = StatusIncidente.ABERTO
    valor_observado: str
    valor_esperado: str
    desvio: str
    justificativa: str
    detectado_em: datetime
    resolvido_em: datetime | None = None


_SQL_INSERIR = """
INSERT INTO observabilidade.incidente (
    dataset, regra, coluna, severidade, status, valor_observado, valor_esperado,
    desvio, justificativa, detectado_em
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_CONSULTAR_ABERTOS = """
SELECT id, dataset, regra, coluna, severidade, status, valor_observado, valor_esperado,
       desvio, justificativa, detectado_em, resolvido_em
FROM observabilidade.incidente
WHERE dataset = ? AND status = 'aberto'
"""

_SQL_RESOLVER = """
UPDATE observabilidade.incidente SET status = 'resolvido', resolvido_em = ? WHERE id = ?
"""


def gravar_incidente(con: duckdb.DuckDBPyConnection, incidente: Incidente) -> None:
    con.execute(
        _SQL_INSERIR,
        [
            incidente.dataset,
            incidente.regra.value,
            incidente.coluna,
            incidente.severidade.value,
            incidente.status.value,
            incidente.valor_observado,
            incidente.valor_esperado,
            incidente.desvio,
            incidente.justificativa,
            incidente.detectado_em,
        ],
    )


def consultar_incidentes_abertos(
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    regra: RegraIncidente | None = None,
    coluna: str | None = None,
) -> list[Incidente]:
    sql = _SQL_CONSULTAR_ABERTOS
    parametros: list[object] = [dataset]
    if regra is not None:
        sql += " AND regra = ?"
        parametros.append(regra.value)
    if coluna is not None:
        sql += " AND coluna = ?"
        parametros.append(coluna)

    linhas = con.execute(sql, parametros).fetchall()
    return [
        Incidente(
            id=linha[0],
            dataset=linha[1],
            regra=RegraIncidente(linha[2]),
            coluna=linha[3],
            severidade=SeveridadeRegra(linha[4]),
            status=StatusIncidente(linha[5]),
            valor_observado=linha[6],
            valor_esperado=linha[7],
            desvio=linha[8],
            justificativa=linha[9],
            detectado_em=linha[10],
            resolvido_em=linha[11],
        )
        for linha in linhas
    ]


def marcar_resolvido(
    con: duckdb.DuckDBPyConnection, incidente_id: int, resolvido_em: datetime
) -> None:
    con.execute(_SQL_RESOLVER, [resolvido_em, incidente_id])

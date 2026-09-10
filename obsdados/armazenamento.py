"""Leitura e escrita do histórico de métricas no metric store."""

import json

import duckdb

from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoAmostragem, TipoMetrica

_SQL_INSERIR = """
INSERT INTO observabilidade.historico_metrica (
    dataset, tipo_metrica, dimensao, coluna, coletado_em, valor, valor_texto, status,
    tipo_amostragem, motivo_nao_suportado, mensagem_erro, backend, linhas_buscadas,
    duracao_segundos, parametros_metrica, chave_idempotencia
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (chave_idempotencia) DO UPDATE SET
    coletado_em = excluded.coletado_em,
    valor = excluded.valor,
    valor_texto = excluded.valor_texto,
    status = excluded.status,
    tipo_amostragem = excluded.tipo_amostragem,
    motivo_nao_suportado = excluded.motivo_nao_suportado,
    mensagem_erro = excluded.mensagem_erro,
    backend = excluded.backend,
    linhas_buscadas = excluded.linhas_buscadas,
    duracao_segundos = excluded.duracao_segundos,
    parametros_metrica = excluded.parametros_metrica
"""

_SQL_CONSULTAR_BASE = """
SELECT dataset, tipo_metrica, dimensao, coluna, status, valor, valor_texto, tipo_amostragem,
       motivo_nao_suportado, mensagem_erro, backend, linhas_buscadas,
       duracao_segundos, coletado_em, parametros_metrica
FROM observabilidade.historico_metrica
WHERE dataset = ?
"""


def _chave_idempotencia(resultado: ResultadoMetrica) -> str:
    """Chave de (dataset, métrica, coluna, dimensão, minuto) — ver README sobre NULL em UNIQUE."""
    minuto = resultado.coletado_em.strftime("%Y-%m-%dT%H:%M")
    partes = [
        resultado.dataset,
        resultado.tipo_metrica.value,
        resultado.coluna or "",
        resultado.dimensao or "",
        minuto,
    ]
    return "|".join(partes)


def gravar_resultado_metrica(con: duckdb.DuckDBPyConnection, resultado: ResultadoMetrica) -> None:
    """Grava um `ResultadoMetrica` como uma linha no histórico (upsert idempotente por minuto)."""
    parametros_json = json.dumps(dict(resultado.parametros)) if resultado.parametros else None
    con.execute(
        _SQL_INSERIR,
        [
            resultado.dataset,
            resultado.tipo_metrica.value,
            resultado.dimensao,
            resultado.coluna,
            resultado.coletado_em,
            resultado.valor,
            resultado.valor_texto,
            resultado.status.value,
            resultado.tipo_amostragem.value,
            resultado.motivo_nao_suportado,
            resultado.mensagem_erro,
            resultado.backend,
            resultado.linhas_buscadas,
            resultado.duracao_segundos,
            parametros_json,
            _chave_idempotencia(resultado),
        ],
    )


def consultar_historico(
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    tipo_metrica: TipoMetrica | None = None,
    coluna: str | None = None,
    limite: int = 100,
) -> list[ResultadoMetrica]:
    """Lê o histórico de um dataset, mais recente primeiro."""
    sql = _SQL_CONSULTAR_BASE
    parametros: list[object] = [dataset]
    if tipo_metrica is not None:
        sql += " AND tipo_metrica = ?"
        parametros.append(tipo_metrica.value)
    if coluna is not None:
        sql += " AND coluna = ?"
        parametros.append(coluna)
    sql += " ORDER BY coletado_em DESC LIMIT ?"
    parametros.append(limite)

    linhas = con.execute(sql, parametros).fetchall()
    return [
        ResultadoMetrica(
            dataset=linha[0],
            tipo_metrica=TipoMetrica(linha[1]),
            dimensao=linha[2],
            coluna=linha[3],
            status=StatusResultadoMetrica(linha[4]),
            valor=linha[5],
            valor_texto=linha[6],
            tipo_amostragem=TipoAmostragem(linha[7]),
            motivo_nao_suportado=linha[8],
            mensagem_erro=linha[9],
            backend=linha[10],
            linhas_buscadas=linha[11],
            duracao_segundos=linha[12],
            coletado_em=linha[13],
            parametros=json.loads(linha[14]) if linha[14] else {},
        )
        for linha in linhas
    ]

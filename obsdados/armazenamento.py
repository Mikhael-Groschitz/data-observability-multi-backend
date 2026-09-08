"""Leitura e escrita do histórico de métricas no metric store."""

import duckdb

from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoAmostragem, TipoMetrica

_SQL_INSERIR = """
INSERT INTO observabilidade.historico_metrica (
    dataset, tipo_metrica, dimensao, coletado_em, valor, status, tipo_amostragem,
    motivo_nao_suportado, mensagem_erro, backend, linhas_buscadas, duracao_segundos,
    parametros_metrica
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SQL_CONSULTAR_BASE = """
SELECT dataset, tipo_metrica, dimensao, status, valor, tipo_amostragem,
       motivo_nao_suportado, mensagem_erro, backend, linhas_buscadas,
       duracao_segundos, coletado_em
FROM observabilidade.historico_metrica
WHERE dataset = ?
"""


def gravar_resultado_metrica(con: duckdb.DuckDBPyConnection, resultado: ResultadoMetrica) -> None:
    """Grava um `ResultadoMetrica` como uma linha no histórico."""
    con.execute(
        _SQL_INSERIR,
        [
            resultado.dataset,
            resultado.tipo_metrica.value,
            resultado.dimensao,
            resultado.coletado_em,
            resultado.valor,
            resultado.status.value,
            resultado.tipo_amostragem.value,
            resultado.motivo_nao_suportado,
            resultado.mensagem_erro,
            resultado.backend,
            resultado.linhas_buscadas,
            resultado.duracao_segundos,
            None,
        ],
    )


def consultar_historico(
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    tipo_metrica: TipoMetrica | None = None,
    limite: int = 100,
) -> list[ResultadoMetrica]:
    """Lê o histórico de um dataset, mais recente primeiro."""
    sql = _SQL_CONSULTAR_BASE
    parametros: list[object] = [dataset]
    if tipo_metrica is not None:
        sql += " AND tipo_metrica = ?"
        parametros.append(tipo_metrica.value)
    sql += " ORDER BY coletado_em DESC LIMIT ?"
    parametros.append(limite)

    linhas = con.execute(sql, parametros).fetchall()
    return [
        ResultadoMetrica(
            dataset=linha[0],
            tipo_metrica=TipoMetrica(linha[1]),
            dimensao=linha[2],
            status=StatusResultadoMetrica(linha[3]),
            valor=linha[4],
            tipo_amostragem=TipoAmostragem(linha[5]),
            motivo_nao_suportado=linha[6],
            mensagem_erro=linha[7],
            backend=linha[8],
            linhas_buscadas=linha[9],
            duracao_segundos=linha[10],
            coletado_em=linha[11],
        )
        for linha in linhas
    ]

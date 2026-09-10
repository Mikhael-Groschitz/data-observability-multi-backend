"""Um ciclo completo para um dataset: coleta o que o contrato pede, avalia, notifica."""

from datetime import datetime

import duckdb

from obsdados.alerta import TipoWebhook, notificar_avaliacao
from obsdados.armazenamento import gravar_resultado_metrica
from obsdados.avaliador import ResultadoAvaliacao, avaliar_dataset
from obsdados.coletor import coletar_metrica
from obsdados.conexao import conectar_origem
from obsdados.contrato import ContratoDataset
from obsdados.nucleo import EspecificacaoMetrica, TipoMetrica


def montar_especificacoes(contrato: ContratoDataset) -> list[EspecificacaoMetrica]:
    """Traduz as regras do contrato nas métricas que precisam ser coletadas para avaliá-las."""
    especificacoes = []
    if contrato.frescor:
        especificacoes.append(
            EspecificacaoMetrica(
                dataset=contrato.dataset,
                tabela=contrato.tabela,
                tipo_metrica=TipoMetrica.FRESCOR,
                coluna=contrato.frescor.coluna,
            )
        )
    if contrato.volume:
        especificacoes.append(
            EspecificacaoMetrica(
                dataset=contrato.dataset,
                tabela=contrato.tabela,
                tipo_metrica=TipoMetrica.CONTAGEM_LINHAS,
            )
        )
    if contrato.schema_:
        especificacoes.append(
            EspecificacaoMetrica(
                dataset=contrato.dataset,
                tabela=contrato.tabela,
                tipo_metrica=TipoMetrica.SCHEMA_HASH,
            )
        )
    for regra in contrato.nulos:
        especificacoes.append(
            EspecificacaoMetrica(
                dataset=contrato.dataset,
                tabela=contrato.tabela,
                tipo_metrica=TipoMetrica.TAXA_NULOS,
                coluna=regra.coluna,
            )
        )
    return especificacoes


def executar_ciclo(
    contrato: ContratoDataset,
    con_store: duckdb.DuckDBPyConnection,
    *,
    webhook_url: str | None,
    webhook_tipo: TipoWebhook,
    agora: datetime | None = None,
) -> ResultadoAvaliacao:
    """Coleta, avalia e notifica um dataset. Uma conexão de origem por ciclo, curta."""
    adaptador, fechar_origem = conectar_origem(contrato.conexao.backend, contrato.conexao.db_origem)
    try:
        for especificacao in montar_especificacoes(contrato):
            resultado_metrica = coletar_metrica(adaptador, especificacao)
            gravar_resultado_metrica(con_store, resultado_metrica)
    finally:
        fechar_origem()

    resultado = avaliar_dataset(contrato, con_store, agora=agora)
    notificar_avaliacao(con_store, contrato, resultado, url=webhook_url, tipo=webhook_tipo)
    return resultado

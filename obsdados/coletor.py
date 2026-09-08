"""Orquestração da coleta: negocia capacidade com o adapter e registra log estruturado."""

from datetime import datetime

from obsdados.adaptador import Adaptador
from obsdados.logging_config import obter_logger
from obsdados.nucleo import (
    CAPACIDADE_POR_TIPO_METRICA,
    EspecificacaoMetrica,
    ResultadoMetrica,
    StatusResultadoMetrica,
)

_logger = obter_logger()


def coletar_metrica(adaptador: Adaptador, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
    """Coleta uma métrica de um adapter, negociando capacidade antes de pedir."""
    capacidade_necessaria = CAPACIDADE_POR_TIPO_METRICA[especificacao.tipo_metrica]
    capacidades = adaptador.capacidades_suportadas()

    if (capacidade_necessaria & capacidades) != capacidade_necessaria:
        resultado = ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            status=StatusResultadoMetrica.NAO_SUPORTADO,
            motivo_nao_suportado=(
                f"backend '{adaptador.nome_backend}' não declara suporte a "
                f"{capacidade_necessaria.name} (necessário para {especificacao.tipo_metrica.value})"
            ),
            backend=adaptador.nome_backend,
            linhas_buscadas=0,
            duracao_segundos=0.0,
            coletado_em=datetime.now(),
        )
    else:
        resultado = adaptador.executar_metrica(especificacao)

    _logger.info(
        "metrica_coletada",
        dataset=resultado.dataset,
        tipo_metrica=resultado.tipo_metrica.value,
        status=resultado.status.value,
        backend=resultado.backend,
        linhas_buscadas=resultado.linhas_buscadas,
        duracao_segundos=resultado.duracao_segundos,
    )
    return resultado

"""Roda o ciclo de coleta+avaliação em intervalo fixo, para um ou mais contratos."""

import time
from collections.abc import Callable, Sequence
from pathlib import Path

import duckdb
import psycopg

from obsdados.alerta import TipoWebhook
from obsdados.avaliador import ResultadoAvaliacao
from obsdados.ciclo import executar_ciclo
from obsdados.conexao import ConfiguracaoOrigemInvalida
from obsdados.contrato import ContratoInvalido, carregar_contrato
from obsdados.db import conectar_escrita
from obsdados.logging_config import obter_logger

_logger = obter_logger()

_ERROS_ORIGEM_INDISPONIVEL = (ConfiguracaoOrigemInvalida, duckdb.Error, psycopg.Error)


def executar_agendador(  # noqa: PLR0913
    caminhos_contrato: Sequence[Path],
    store: str,
    *,
    webhook_url: str | None,
    webhook_tipo: TipoWebhook,
    intervalo_segundos: float,
    ciclos: int | None = None,
    dormir: Callable[[float], None] = time.sleep,
    ao_avaliar: Callable[[str, ResultadoAvaliacao], None] | None = None,
) -> None:
    """Roda `ciclos` rodadas (ou pra sempre, se `None`), dormindo entre elas."""
    ciclo_atual = 0
    while ciclos is None or ciclo_atual < ciclos:
        for caminho in caminhos_contrato:
            resultado = _executar_um_contrato(caminho, store, webhook_url, webhook_tipo)
            if resultado is not None and ao_avaliar is not None:
                dataset, avaliacao = resultado
                ao_avaliar(dataset, avaliacao)
        ciclo_atual += 1
        if ciclos is None or ciclo_atual < ciclos:
            dormir(intervalo_segundos)


def _executar_um_contrato(
    caminho: Path, store: str, webhook_url: str | None, webhook_tipo: TipoWebhook
) -> tuple[str, ResultadoAvaliacao] | None:
    try:
        contrato = carregar_contrato(str(caminho))
    except ContratoInvalido as erro:
        _logger.warning("contrato_invalido", caminho=str(caminho), erro=str(erro))
        return None

    con = conectar_escrita(store)
    try:
        try:
            resultado = executar_ciclo(
                contrato, con, webhook_url=webhook_url, webhook_tipo=webhook_tipo
            )
        except _ERROS_ORIGEM_INDISPONIVEL as erro:
            _logger.warning("origem_indisponivel", dataset=contrato.dataset, erro=str(erro))
            return None
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return contrato.dataset, resultado

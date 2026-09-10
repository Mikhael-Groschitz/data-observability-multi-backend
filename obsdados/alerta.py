"""Alerta por webhook: corpo legível, deduplicado e agrupado numa janela de silêncio."""

from datetime import datetime, timedelta
from enum import StrEnum

import duckdb
import httpx

from obsdados.avaliador import ResultadoAvaliacao
from obsdados.contrato import ContratoDataset
from obsdados.incidente import Incidente
from obsdados.logging_config import obter_logger
from obsdados.notificacao import buscar_estado, montar_chave, registrar_envio, registrar_supressao

_logger = obter_logger()


class TipoWebhook(StrEnum):
    DISCORD = "discord"
    SLACK = "slack"


class EventoAlerta(StrEnum):
    ABERTO = "aberto"
    RESOLVIDO = "resolvido"


def formatar_mensagem(incidente: Incidente, evento: EventoAlerta, suprimidas: int = 0) -> str:
    if evento == EventoAlerta.RESOLVIDO:
        texto = f"[RESOLVIDO] {incidente.dataset} - {incidente.regra.value} voltou ao normal."
    else:
        alvo = f" (coluna {incidente.coluna})" if incidente.coluna else ""
        texto = (
            f"[{incidente.severidade.value.upper()}] {incidente.dataset} - "
            f"{incidente.regra.value}{alvo}\n"
            f"Observado: {incidente.valor_observado}\n"
            f"Esperado: {incidente.valor_esperado}\n"
            f"Desvio: {incidente.desvio}\n"
            f"{incidente.justificativa}"
        )
    if suprimidas > 0:
        texto += f"\n(mais {suprimidas} ocorrência(s) agrupada(s) na janela de silêncio)"
    return texto


def _montar_payload(tipo: TipoWebhook, texto: str) -> dict[str, object]:
    if tipo == TipoWebhook.DISCORD:
        return {"content": texto}
    return {"text": texto}


def enviar_webhook(url: str, tipo: TipoWebhook, texto: str, *, timeout: float = 5.0) -> None:
    resposta = httpx.post(url, json=_montar_payload(tipo, texto), timeout=timeout)
    resposta.raise_for_status()


def notificar_incidente(  # noqa: PLR0913
    con: duckdb.DuckDBPyConnection,
    incidente: Incidente,
    evento: EventoAlerta,
    *,
    url: str,
    tipo: TipoWebhook,
    janela_silencio_minutos: int,
    agora: datetime | None = None,
) -> bool:
    """Envia (ou agrupa dentro da janela) uma notificação. Devolve se enviou (ver README)."""
    momento = agora or datetime.now()
    chave = montar_chave(incidente.dataset, incidente.regra.value, incidente.coluna)
    estado = buscar_estado(con, chave)

    dentro_da_janela = (
        estado is not None
        and estado.ultimo_evento == evento.value
        and momento - estado.ultima_notificacao_em < timedelta(minutes=janela_silencio_minutos)
    )
    if dentro_da_janela and estado is not None:
        registrar_supressao(con, estado)
        return False

    suprimidas = estado.suprimidas if estado is not None else 0
    texto = formatar_mensagem(incidente, evento, suprimidas=suprimidas)
    enviar_webhook(url, tipo, texto)
    registrar_envio(
        con, incidente.dataset, incidente.regra.value, incidente.coluna, evento.value, momento
    )
    return True


def notificar_avaliacao(
    con: duckdb.DuckDBPyConnection,
    contrato: ContratoDataset,
    resultado: ResultadoAvaliacao,
    *,
    url: str | None,
    tipo: TipoWebhook,
) -> None:
    """Notifica cada incidente aberto/resolvido desta rodada. Falha de webhook não propaga."""
    if not contrato.alertas.ativo or not url:
        return
    janela = contrato.alertas.janela_silencio_minutos
    for incidente in resultado.abertos:
        _notificar_sem_derrubar_o_ciclo(con, incidente, EventoAlerta.ABERTO, url, tipo, janela)
    for incidente in resultado.resolvidos:
        _notificar_sem_derrubar_o_ciclo(con, incidente, EventoAlerta.RESOLVIDO, url, tipo, janela)


def _notificar_sem_derrubar_o_ciclo(  # noqa: PLR0913, PLR0917
    con: duckdb.DuckDBPyConnection,
    incidente: Incidente,
    evento: EventoAlerta,
    url: str,
    tipo: TipoWebhook,
    janela_silencio_minutos: int,
) -> None:
    try:
        notificar_incidente(
            con,
            incidente,
            evento,
            url=url,
            tipo=tipo,
            janela_silencio_minutos=janela_silencio_minutos,
        )
    except httpx.HTTPError as erro:
        _logger.warning(
            "falha_ao_notificar",
            dataset=incidente.dataset,
            regra=incidente.regra.value,
            erro=str(erro),
        )

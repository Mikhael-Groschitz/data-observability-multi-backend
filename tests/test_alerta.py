"""Testa o alerta por webhook contra um servidor HTTP real (não um mock)."""

from datetime import datetime, timedelta

from obsdados.alerta import (
    EventoAlerta,
    TipoWebhook,
    enviar_webhook,
    formatar_mensagem,
    notificar_incidente,
)
from obsdados.db import conectar_escrita
from obsdados.incidente import Incidente, RegraIncidente, SeveridadeRegra
from tests.conftest import ServidorWebhook


def _incidente(**overrides: object) -> Incidente:
    campos: dict[str, object] = {
        "dataset": "vendas.pedidos",
        "regra": RegraIncidente.VOLUME,
        "coluna": None,
        "severidade": SeveridadeRegra.CRITICO,
        "valor_observado": "500 linhas",
        "valor_esperado": "1000 linhas",
        "desvio": "8.0 MADs",
        "justificativa": "volume caiu pela metade",
        "detectado_em": datetime.now(),
    }
    campos.update(overrides)
    return Incidente(**campos)


def test_enviar_webhook_discord_manda_content(servidor_webhook: ServidorWebhook) -> None:
    enviar_webhook(servidor_webhook.url, TipoWebhook.DISCORD, "mensagem de teste")

    assert servidor_webhook.requisicoes == [{"content": "mensagem de teste"}]


def test_enviar_webhook_slack_manda_text(servidor_webhook: ServidorWebhook) -> None:
    enviar_webhook(servidor_webhook.url, TipoWebhook.SLACK, "mensagem de teste")

    assert servidor_webhook.requisicoes == [{"text": "mensagem de teste"}]


def test_formatar_mensagem_e_legivel_nao_e_dump_de_json() -> None:
    texto = formatar_mensagem(_incidente(), EventoAlerta.ABERTO)

    assert "volume caiu pela metade" in texto
    assert "500 linhas" in texto
    assert "1000 linhas" in texto
    assert not texto.startswith("{")


def test_formatar_mensagem_resolvido() -> None:
    texto = formatar_mensagem(_incidente(), EventoAlerta.RESOLVIDO)

    assert "RESOLVIDO" in texto
    assert "voltou ao normal" in texto


def test_formatar_mensagem_inclui_supressoes_quando_houver() -> None:
    texto = formatar_mensagem(_incidente(), EventoAlerta.ABERTO, suprimidas=3)

    assert "3 ocorrência" in texto


def test_notificar_incidente_envia_na_primeira_vez(servidor_webhook: ServidorWebhook) -> None:
    con = conectar_escrita(":memory:")

    enviou = notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
    )

    assert enviou is True
    assert len(servidor_webhook.requisicoes) == 1


def test_notificar_incidente_agrupa_dentro_da_janela(servidor_webhook: ServidorWebhook) -> None:
    con = conectar_escrita(":memory:")
    agora = datetime(2026, 1, 5, 10, 0)

    notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora,
    )
    enviou_de_novo = notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora + timedelta(minutes=5),
    )

    assert enviou_de_novo is False
    assert len(servidor_webhook.requisicoes) == 1


def test_notificar_incidente_envia_de_novo_apos_janela_com_contagem_suprimida(
    servidor_webhook: ServidorWebhook,
) -> None:
    con = conectar_escrita(":memory:")
    agora = datetime(2026, 1, 5, 10, 0)

    notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora,
    )
    notificar_incidente(  # suprimida (5 min depois, dentro da janela de 30 min)
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora + timedelta(minutes=5),
    )
    enviou_apos_janela = notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora + timedelta(minutes=40),
    )

    assert enviou_apos_janela is True
    assert len(servidor_webhook.requisicoes) == 2
    assert "1 ocorrência" in servidor_webhook.requisicoes[1]["content"]


def test_notificar_resolvido_nao_e_suprimido_pela_janela_do_aberto(
    servidor_webhook: ServidorWebhook,
) -> None:
    """Sem essa distinção, um incidente que resolve rápido nunca manda o encerramento."""
    con = conectar_escrita(":memory:")
    agora = datetime(2026, 1, 5, 10, 0)

    notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.ABERTO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora,
    )
    enviou_resolvido = notificar_incidente(
        con,
        _incidente(),
        EventoAlerta.RESOLVIDO,
        url=servidor_webhook.url,
        tipo=TipoWebhook.DISCORD,
        janela_silencio_minutos=30,
        agora=agora + timedelta(minutes=2),
    )

    assert enviou_resolvido is True
    assert len(servidor_webhook.requisicoes) == 2
    assert "RESOLVIDO" in servidor_webhook.requisicoes[1]["content"]

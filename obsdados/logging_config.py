"""Configuração de log estruturado em JSON, escrito em stderr."""

import sys
from typing import Any

import structlog


class _LoggerStderr:
    """Resolve `sys.stderr` a cada chamada, não uma vez na configuração.

    Evita escrever num arquivo antigo se o processo trocar stderr depois de
    configurado — é o que o `capsys` do pytest faz a cada teste.
    """

    def msg(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    debug = msg
    info = msg
    warning = msg
    error = msg
    critical = msg
    exception = msg


def _fabrica_logger(*_args: object) -> _LoggerStderr:
    return _LoggerStderr()


def configurar_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=_fabrica_logger,
    )


def obter_logger() -> Any:
    return structlog.get_logger()

"""Testa a consistência estrutural de `ResultadoMetrica`."""

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoMetrica


def _campos_base(**sobrescritas: Any) -> dict[str, Any]:
    campos: dict[str, Any] = {
        "dataset": "ds",
        "tipo_metrica": TipoMetrica.CONTAGEM_LINHAS,
        "dimensao": None,
        "status": StatusResultadoMetrica.OK,
        "valor": 1.0,
        "backend": "duckdb",
        "linhas_buscadas": 1,
        "duracao_segundos": 0.01,
        "coletado_em": datetime.now(),
    }
    campos.update(sobrescritas)
    return campos


def test_status_ok_exige_valor_nao_nulo() -> None:
    with pytest.raises(ValidationError):
        ResultadoMetrica(**_campos_base(status=StatusResultadoMetrica.OK, valor=None))


def test_status_ok_com_valor_e_valido() -> None:
    resultado = ResultadoMetrica(**_campos_base(valor=42.0))
    assert resultado.valor == 42.0


def test_status_nao_suportado_exige_motivo() -> None:
    with pytest.raises(ValidationError):
        ResultadoMetrica(
            **_campos_base(
                status=StatusResultadoMetrica.NAO_SUPORTADO,
                valor=None,
                motivo_nao_suportado=None,
            )
        )


def test_status_nao_suportado_com_motivo_e_valido() -> None:
    resultado = ResultadoMetrica(
        **_campos_base(
            status=StatusResultadoMetrica.NAO_SUPORTADO,
            valor=None,
            motivo_nao_suportado="sem capacidade",
        )
    )
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO


def test_status_erro_exige_mensagem() -> None:
    with pytest.raises(ValidationError):
        ResultadoMetrica(
            **_campos_base(status=StatusResultadoMetrica.ERRO, valor=None, mensagem_erro=None)
        )


def test_status_erro_com_mensagem_e_valido() -> None:
    resultado = ResultadoMetrica(
        **_campos_base(
            status=StatusResultadoMetrica.ERRO, valor=None, mensagem_erro="tabela não existe"
        )
    )
    assert resultado.status == StatusResultadoMetrica.ERRO

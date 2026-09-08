"""Testa a negociação de capacidade do coletor com um adapter fake."""

from datetime import datetime

import pytest

from obsdados.coletor import coletar_metrica
from obsdados.logging_config import configurar_logging
from obsdados.nucleo import (
    Capacidade,
    ColunaSchema,
    DescricaoDataset,
    EspecificacaoMetrica,
    ResultadoMetrica,
    StatusResultadoMetrica,
    TipoMetrica,
)


class _AdaptadorFake:
    nome_backend = "fake"

    def __init__(self, capacidades: Capacidade, chamadas: list[bool]) -> None:
        self._capacidades = capacidades
        self._chamadas = chamadas

    def listar_datasets(self) -> list[DescricaoDataset]:
        return []

    def descrever_schema(self, tabela: str) -> list[ColunaSchema]:
        return []

    def capacidades_suportadas(self) -> Capacidade:
        return self._capacidades

    def executar_metrica(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        self._chamadas.append(True)
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            status=StatusResultadoMetrica.OK,
            valor=1.0,
            backend=self.nome_backend,
            linhas_buscadas=1,
            duracao_segundos=0.001,
            coletado_em=datetime.now(),
        )


def _especificacao() -> EspecificacaoMetrica:
    return EspecificacaoMetrica(dataset="ds", tabela="t", tipo_metrica=TipoMetrica.CONTAGEM_LINHAS)


def test_capacidade_ausente_nunca_chama_executar_metrica() -> None:
    chamadas: list[bool] = []
    adaptador = _AdaptadorFake(Capacidade.NENHUMA, chamadas)

    resultado = coletar_metrica(adaptador, _especificacao())

    assert chamadas == []
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO
    assert resultado.motivo_nao_suportado is not None


def test_capacidade_presente_chama_executar_metrica() -> None:
    chamadas: list[bool] = []
    adaptador = _AdaptadorFake(Capacidade.CONTAGEM_LINHAS, chamadas)

    resultado = coletar_metrica(adaptador, _especificacao())

    assert chamadas == [True]
    assert resultado.status == StatusResultadoMetrica.OK


def test_log_estruturado_emitido(capsys: pytest.CaptureFixture[str]) -> None:
    configurar_logging()
    adaptador = _AdaptadorFake(Capacidade.CONTAGEM_LINHAS, [])

    coletar_metrica(adaptador, _especificacao())

    saida = capsys.readouterr()
    assert "metrica_coletada" in saida.err
    assert "dataset" in saida.err

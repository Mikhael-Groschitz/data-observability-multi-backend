"""Prova que o contrato de push-down tem dente: um adapter ruim de verdade o quebra."""

import time
from datetime import datetime

import duckdb
import pytest

from obsdados.instrumentacao import ConexaoInstrumentadaDuckDB
from obsdados.nucleo import (
    LIMITE_LINHAS_POR_METRICA,
    Capacidade,
    ColunaSchema,
    DescricaoDataset,
    EspecificacaoMetrica,
    ResultadoMetrica,
    StatusResultadoMetrica,
    TipoAmostragem,
    TipoMetrica,
)

from ..conftest import TabelaTeste
from ._asserts import assert_respeita_limite_pushdown


class AdaptadorRuimSelectStar:
    """Faz SELECT * e conta em Python — deliberadamente errado, só para este teste."""

    nome_backend = "ruim_select_star"

    def __init__(self, conexao: duckdb.DuckDBPyConnection) -> None:
        self._conexao = conexao

    def listar_datasets(self) -> list[DescricaoDataset]:
        return []

    def descrever_schema(self, tabela: str) -> list[ColunaSchema]:
        return []

    def capacidades_suportadas(self) -> Capacidade:
        return Capacidade.CONTAGEM_LINHAS

    def executar_metrica(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        sql = f"SELECT * FROM {especificacao.tabela}"  # noqa: S608
        linhas = instrumentada.execute(sql).fetchall()
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            status=StatusResultadoMetrica.OK,
            valor=float(len(linhas)),
            tipo_amostragem=TipoAmostragem.FULL_SCAN,
            backend=self.nome_backend,
            linhas_buscadas=instrumentada.linhas_buscadas_total,
            duracao_segundos=time.perf_counter() - inicio,
            coletado_em=datetime.now(),
        )


def test_adaptador_ruim_select_star_falha_o_contrato_de_pushdown(
    tabela_teste_com_mil_linhas: TabelaTeste,
) -> None:
    adaptador = AdaptadorRuimSelectStar(tabela_teste_com_mil_linhas.conexao)
    especificacao = EspecificacaoMetrica(
        dataset="ds",
        tabela=tabela_teste_com_mil_linhas.nome,
        tipo_metrica=TipoMetrica.CONTAGEM_LINHAS,
    )

    resultado = adaptador.executar_metrica(especificacao)

    assert resultado.linhas_buscadas > LIMITE_LINHAS_POR_METRICA
    with pytest.raises(AssertionError):
        assert_respeita_limite_pushdown(resultado)

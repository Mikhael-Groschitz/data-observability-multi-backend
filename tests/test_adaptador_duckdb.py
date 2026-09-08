"""Testa o adapter DuckDB: capacidades, catálogo e execução de métrica."""

from collections.abc import Iterator

import duckdb
import pytest

from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.nucleo import Capacidade, EspecificacaoMetrica, StatusResultadoMetrica, TipoMetrica


@pytest.fixture
def conexao_com_tabela() -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA vendas")
    con.execute("CREATE TABLE vendas.pedidos AS SELECT * FROM range(7) AS t(id)")
    yield con
    con.close()


def test_capacidades_suportadas(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    assert adaptador.capacidades_suportadas() == Capacidade.CONTAGEM_LINHAS


def test_listar_datasets(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    nomes = {dataset.tabela for dataset in adaptador.listar_datasets()}
    assert "pedidos" in nomes


def test_descrever_schema(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    colunas = adaptador.descrever_schema("vendas.pedidos")
    assert [coluna.nome for coluna in colunas] == ["id"]


def test_executar_metrica_contagem_linhas_ok(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    especificacao = EspecificacaoMetrica(
        dataset="vendas.pedidos", tabela="vendas.pedidos", tipo_metrica=TipoMetrica.CONTAGEM_LINHAS
    )
    resultado = adaptador.executar_metrica(especificacao)
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 7.0


class _AdaptadorDuckDBSemCapacidade(AdaptadorDuckDB):
    """Variante de teste que declara não suportar nada, para exercitar o caminho NAO_SUPORTADO."""

    def capacidades_suportadas(self) -> Capacidade:
        return Capacidade.NENHUMA


def test_executar_metrica_nao_suportado_quando_capacidade_ausente(
    conexao_com_tabela: duckdb.DuckDBPyConnection,
) -> None:
    adaptador = _AdaptadorDuckDBSemCapacidade(conexao_com_tabela)
    especificacao = EspecificacaoMetrica(
        dataset="vendas.pedidos", tabela="vendas.pedidos", tipo_metrica=TipoMetrica.CONTAGEM_LINHAS
    )
    resultado = adaptador.executar_metrica(especificacao)
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO
    assert resultado.motivo_nao_suportado is not None


def test_executar_metrica_erro_quando_tabela_nao_existe(
    conexao_com_tabela: duckdb.DuckDBPyConnection,
) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    especificacao = EspecificacaoMetrica(
        dataset="ds", tabela="tabela_inexistente", tipo_metrica=TipoMetrica.CONTAGEM_LINHAS
    )
    resultado = adaptador.executar_metrica(especificacao)
    assert resultado.status == StatusResultadoMetrica.ERRO
    assert resultado.mensagem_erro is not None

"""Testa o adapter DuckDB: capacidades, catálogo e todo o catálogo de métricas."""

from collections.abc import Iterator

import duckdb
import pytest

from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.nucleo import (
    GRANULARIDADE_DIA,
    PARAMETRO_GRANULARIDADE,
    PARAMETRO_PERMITE_VALOR,
    PARAMETRO_QUANTIL,
    Capacidade,
    EspecificacaoMetrica,
    StatusResultadoMetrica,
    TipoAmostragem,
    TipoMetrica,
)


@pytest.fixture
def conexao_com_tabela() -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA vendas")
    con.execute(
        """
        CREATE TABLE vendas.pedidos AS
        SELECT
            i AS id,
            (i % 5 = 0) AS valor_nulo_flag,
            CASE WHEN i % 5 = 0 THEN NULL ELSE i * 1.5 END AS valor,
            now() - to_seconds(i * 3600) AS criado_em,
            (['norte', 'sul', 'leste'])[1 + (i % 3)] AS regiao
        FROM range(7) AS t(i)
        """
    )
    yield con
    con.close()


def _especificacao(**overrides: object) -> EspecificacaoMetrica:
    campos: dict[str, object] = {
        "dataset": "vendas.pedidos",
        "tabela": "vendas.pedidos",
        "tipo_metrica": TipoMetrica.CONTAGEM_LINHAS,
    }
    campos.update(overrides)
    return EspecificacaoMetrica(**campos)


def test_capacidades_suportadas_inclui_contagem_linhas(
    conexao_com_tabela: duckdb.DuckDBPyConnection,
) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    capacidades = adaptador.capacidades_suportadas()
    assert Capacidade.CONTAGEM_LINHAS in capacidades
    assert Capacidade.CONTAGEM_DISTINTOS_APROXIMADA in capacidades


def test_listar_datasets(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    nomes = {dataset.tabela for dataset in adaptador.listar_datasets()}
    assert "pedidos" in nomes


def test_descrever_schema(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    colunas = adaptador.descrever_schema("vendas.pedidos")
    assert {coluna.nome for coluna in colunas} == {
        "id", "valor_nulo_flag", "valor", "criado_em", "regiao",
    }


def test_contagem_linhas_ok(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao())
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 7.0


def test_contagem_por_particao_exata(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(coluna="regiao", dimensao="norte")
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 3.0  # i=0,3,6 -> ['norte','sul','leste'][0] == norte


def test_contagem_por_dia(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    hoje = duckdb.connect(":memory:").execute("SELECT strftime(now(), '%Y-%m-%d')").fetchone()
    assert hoje is not None
    resultado = adaptador.executar_metrica(
        _especificacao(
            coluna="criado_em",
            dimensao=hoje[0],
            parametros={PARAMETRO_GRANULARIDADE: GRANULARIDADE_DIA},
        )
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None
    assert resultado.valor >= 1.0


def test_frescor_ok(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.FRESCOR, coluna="criado_em")
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None
    assert resultado.valor >= 0


def test_frescor_sem_coluna_e_erro(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao(tipo_metrica=TipoMetrica.FRESCOR))
    assert resultado.status == StatusResultadoMetrica.ERRO


def test_schema_hash_estavel_entre_chamadas(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    especificacao = _especificacao(tipo_metrica=TipoMetrica.SCHEMA_HASH)
    primeiro = adaptador.executar_metrica(especificacao)
    segundo = adaptador.executar_metrica(especificacao)
    assert primeiro.status == StatusResultadoMetrica.OK
    assert primeiro.valor_texto == segundo.valor_texto
    assert primeiro.valor_texto is not None


def test_taxa_nulos_ok(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.TAXA_NULOS, coluna="valor")
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None
    assert resultado.valor > 0
    assert resultado.tipo_amostragem == TipoAmostragem.FULL_SCAN


def test_cardinalidade_ok(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.CARDINALIDADE, coluna="regiao")
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 3.0


def test_minimo_bloqueado_por_politica_padrao(
    conexao_com_tabela: duckdb.DuckDBPyConnection,
) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.MINIMO, coluna="valor")
    )
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO
    assert resultado.motivo_nao_suportado is not None


def test_maximo_liberado_com_permite_valor(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(
            tipo_metrica=TipoMetrica.MAXIMO,
            coluna="valor",
            parametros={PARAMETRO_PERMITE_VALOR: True},
        )
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor_texto == "9.0"


def test_quantil_liberado_com_permite_valor(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(
            tipo_metrica=TipoMetrica.QUANTIL,
            coluna="valor",
            parametros={PARAMETRO_QUANTIL: 0.5, PARAMETRO_PERMITE_VALOR: True},
        )
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None


def test_quantil_invalido_e_erro(conexao_com_tabela: duckdb.DuckDBPyConnection) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(
            tipo_metrica=TipoMetrica.QUANTIL,
            coluna="valor",
            parametros={PARAMETRO_QUANTIL: 1.5, PARAMETRO_PERMITE_VALOR: True},
        )
    )
    assert resultado.status == StatusResultadoMetrica.ERRO


class _AdaptadorDuckDBSemCapacidade(AdaptadorDuckDB):
    """Variante de teste que declara não suportar nada, para exercitar o caminho NAO_SUPORTADO."""

    def capacidades_suportadas(self) -> Capacidade:
        return Capacidade.NENHUMA


def test_executar_metrica_nao_suportado_quando_capacidade_ausente(
    conexao_com_tabela: duckdb.DuckDBPyConnection,
) -> None:
    adaptador = _AdaptadorDuckDBSemCapacidade(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao())
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO
    assert resultado.motivo_nao_suportado is not None


def test_executar_metrica_erro_quando_tabela_nao_existe(
    conexao_com_tabela: duckdb.DuckDBPyConnection,
) -> None:
    adaptador = AdaptadorDuckDB(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao(tabela="tabela_inexistente"))
    assert resultado.status == StatusResultadoMetrica.ERRO
    assert resultado.mensagem_erro is not None

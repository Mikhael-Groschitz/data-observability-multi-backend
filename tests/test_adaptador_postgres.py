"""Testa o adapter Postgres: mesmo catálogo de métricas do DuckDB, dialeto diferente.

Pula automaticamente (via fixture `conexao_postgres`) se não houver Postgres de
teste acessível — ver `docker-compose.yml` para subir um local.
"""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from obsdados.adaptadores.adaptador_postgres import AdaptadorPostgres
from obsdados.nucleo import (
    PARAMETRO_PERMITE_VALOR,
    PARAMETRO_QUANTIL,
    Capacidade,
    EspecificacaoMetrica,
    StatusResultadoMetrica,
    TipoMetrica,
)


@pytest.fixture
def conexao_com_tabela(
    conexao_postgres: "psycopg.Connection[Any]",
) -> Iterator["psycopg.Connection[Any]"]:
    conexao_postgres.execute("CREATE SCHEMA IF NOT EXISTS vendas")
    conexao_postgres.execute("DROP TABLE IF EXISTS vendas.pedidos")
    conexao_postgres.execute(
        """
        CREATE TABLE vendas.pedidos (
            id INTEGER,
            valor NUMERIC,
            criado_em TIMESTAMP,
            regiao TEXT
        )
        """
    )
    conexao_postgres.execute(
        """
        INSERT INTO vendas.pedidos (id, valor, criado_em, regiao)
        SELECT
            i,
            CASE WHEN i % 5 = 0 THEN NULL ELSE i * 1.5 END,
            now() - (i || ' hours')::interval,
            (ARRAY['norte', 'sul', 'leste'])[1 + (i % 3)]
        FROM generate_series(0, 6) AS t(i)
        """
    )
    conexao_postgres.commit()
    yield conexao_postgres


def _especificacao(**overrides: object) -> EspecificacaoMetrica:
    campos: dict[str, object] = {
        "dataset": "vendas.pedidos",
        "tabela": "vendas.pedidos",
        "tipo_metrica": TipoMetrica.CONTAGEM_LINHAS,
    }
    campos.update(overrides)
    return EspecificacaoMetrica(**campos)


def test_capacidades_nao_inclui_cardinalidade(
    conexao_com_tabela: "psycopg.Connection[Any]",
) -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    capacidades = adaptador.capacidades_suportadas()
    assert Capacidade.CONTAGEM_LINHAS in capacidades
    assert Capacidade.CONTAGEM_DISTINTOS_APROXIMADA not in capacidades


def test_listar_datasets(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    nomes = {dataset.tabela for dataset in adaptador.listar_datasets()}
    assert "pedidos" in nomes


def test_descrever_schema(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    colunas = adaptador.descrever_schema("vendas.pedidos")
    assert {coluna.nome for coluna in colunas} == {"id", "valor", "criado_em", "regiao"}


def test_contagem_linhas_ok(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao())
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 7.0


def test_contagem_por_particao_exata(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao(coluna="regiao", dimensao="norte"))
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 3.0


def test_frescor_ok(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.FRESCOR, coluna="criado_em")
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None
    assert resultado.valor >= 0


def test_schema_hash_estavel(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    especificacao = _especificacao(tipo_metrica=TipoMetrica.SCHEMA_HASH)
    primeiro = adaptador.executar_metrica(especificacao)
    segundo = adaptador.executar_metrica(especificacao)
    assert primeiro.valor_texto == segundo.valor_texto
    assert primeiro.valor_texto is not None


def test_taxa_nulos_ok(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.TAXA_NULOS, coluna="valor")
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None
    assert resultado.valor > 0


def test_cardinalidade_nao_suportado(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.CARDINALIDADE, coluna="regiao")
    )
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO


def test_minimo_bloqueado_por_politica_padrao(
    conexao_com_tabela: "psycopg.Connection[Any]",
) -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(tipo_metrica=TipoMetrica.MINIMO, coluna="valor")
    )
    assert resultado.status == StatusResultadoMetrica.NAO_SUPORTADO


def test_maximo_liberado_com_permite_valor(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(
            tipo_metrica=TipoMetrica.MAXIMO,
            coluna="valor",
            parametros={PARAMETRO_PERMITE_VALOR: True},
        )
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor_texto is not None


def test_quantil_liberado_com_permite_valor(conexao_com_tabela: "psycopg.Connection[Any]") -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(
        _especificacao(
            tipo_metrica=TipoMetrica.QUANTIL,
            coluna="valor",
            parametros={PARAMETRO_QUANTIL: 0.5, PARAMETRO_PERMITE_VALOR: True},
        )
    )
    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor is not None


def test_executar_metrica_erro_quando_tabela_nao_existe(
    conexao_com_tabela: "psycopg.Connection[Any]",
) -> None:
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    resultado = adaptador.executar_metrica(_especificacao(tabela="tabela_inexistente"))
    assert resultado.status == StatusResultadoMetrica.ERRO
    assert resultado.mensagem_erro is not None


def test_erro_nao_deixa_conexao_travada_para_a_proxima_chamada(
    conexao_com_tabela: "psycopg.Connection[Any]",
) -> None:
    """Sem o `rollback()` no bloco de exceção, esta segunda chamada falharia."""
    adaptador = AdaptadorPostgres(conexao_com_tabela)
    adaptador.executar_metrica(_especificacao(tabela="tabela_inexistente"))

    resultado = adaptador.executar_metrica(_especificacao())

    assert resultado.status == StatusResultadoMetrica.OK
    assert resultado.valor == 7.0

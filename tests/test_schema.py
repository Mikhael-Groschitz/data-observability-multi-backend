"""Testa o hash de schema e a classificação de mudança aditiva vs. quebradora."""

from obsdados.nucleo import ColunaSchema
from obsdados.schema import (
    ClassificacaoMudancaSchema,
    calcular_hash_schema,
    classificar_mudanca_schema,
)


def _colunas(*definicoes: tuple[str, str, bool]) -> list[ColunaSchema]:
    return [
        ColunaSchema(nome=nome, tipo=tipo, aceita_nulo=aceita_nulo)
        for nome, tipo, aceita_nulo in definicoes
    ]


def test_hash_e_igual_para_mesmo_conjunto_em_ordem_diferente() -> None:
    a = _colunas(("id", "INTEGER", False), ("nome", "VARCHAR", True))
    b = _colunas(("nome", "VARCHAR", True), ("id", "INTEGER", False))
    assert calcular_hash_schema(a) == calcular_hash_schema(b)


def test_hash_muda_quando_tipo_muda() -> None:
    a = _colunas(("id", "INTEGER", False))
    b = _colunas(("id", "BIGINT", False))
    assert calcular_hash_schema(a) != calcular_hash_schema(b)


def test_classificacao_sem_mudanca() -> None:
    a = _colunas(("id", "INTEGER", False), ("nome", "VARCHAR", True))
    classificacao, _ = classificar_mudanca_schema(a, a)
    assert classificacao == ClassificacaoMudancaSchema.SEM_MUDANCA


def test_classificacao_aditiva_coluna_nova() -> None:
    anterior = _colunas(("id", "INTEGER", False))
    atual = _colunas(("id", "INTEGER", False), ("nome", "VARCHAR", True))
    classificacao, motivo = classificar_mudanca_schema(anterior, atual)
    assert classificacao == ClassificacaoMudancaSchema.ADITIVA
    assert "nome" in motivo


def test_classificacao_aditiva_coluna_ficou_opcional() -> None:
    anterior = _colunas(("id", "INTEGER", False))
    atual = _colunas(("id", "INTEGER", True))
    classificacao, _ = classificar_mudanca_schema(anterior, atual)
    assert classificacao == ClassificacaoMudancaSchema.ADITIVA


def test_classificacao_quebradora_coluna_removida() -> None:
    anterior = _colunas(("id", "INTEGER", False), ("nome", "VARCHAR", True))
    atual = _colunas(("id", "INTEGER", False))
    classificacao, motivo = classificar_mudanca_schema(anterior, atual)
    assert classificacao == ClassificacaoMudancaSchema.QUEBRADORA
    assert "nome" in motivo


def test_classificacao_quebradora_tipo_alterado() -> None:
    anterior = _colunas(("id", "INTEGER", False))
    atual = _colunas(("id", "VARCHAR", False))
    classificacao, _ = classificar_mudanca_schema(anterior, atual)
    assert classificacao == ClassificacaoMudancaSchema.QUEBRADORA


def test_classificacao_quebradora_coluna_ficou_obrigatoria() -> None:
    anterior = _colunas(("id", "INTEGER", True))
    atual = _colunas(("id", "INTEGER", False))
    classificacao, _ = classificar_mudanca_schema(anterior, atual)
    assert classificacao == ClassificacaoMudancaSchema.QUEBRADORA


def test_remocao_tem_prioridade_sobre_adicao() -> None:
    anterior = _colunas(("id", "INTEGER", False), ("antiga", "VARCHAR", True))
    atual = _colunas(("id", "INTEGER", False), ("nova", "VARCHAR", True))
    classificacao, motivo = classificar_mudanca_schema(anterior, atual)
    assert classificacao == ClassificacaoMudancaSchema.QUEBRADORA
    assert "antiga" in motivo

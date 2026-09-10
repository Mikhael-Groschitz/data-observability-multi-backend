"""Hash de schema e classificação de mudança entre duas versões."""

import hashlib
from enum import StrEnum

from obsdados.nucleo import ColunaSchema


class ClassificacaoMudancaSchema(StrEnum):
    SEM_MUDANCA = "sem_mudanca"
    ADITIVA = "aditiva"
    QUEBRADORA = "quebradora"


def calcular_hash_schema(colunas: list[ColunaSchema]) -> str:
    canonico = "|".join(sorted(f"{c.nome}:{c.tipo}:{c.aceita_nulo}" for c in colunas))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def classificar_mudanca_schema(
    anterior: list[ColunaSchema], atual: list[ColunaSchema]
) -> tuple[ClassificacaoMudancaSchema, str]:
    """Compara dois snapshots de schema e classifica a mudança (ver README)."""
    por_nome_anterior = {c.nome: c for c in anterior}
    por_nome_atual = {c.nome: c for c in atual}

    removidas = por_nome_anterior.keys() - por_nome_atual.keys()
    adicionadas = por_nome_atual.keys() - por_nome_anterior.keys()
    em_comum = por_nome_anterior.keys() & por_nome_atual.keys()

    tipo_alterado = {
        nome for nome in em_comum if por_nome_anterior[nome].tipo != por_nome_atual[nome].tipo
    }
    ficou_mais_restrita = {
        nome
        for nome in em_comum
        if por_nome_anterior[nome].aceita_nulo and not por_nome_atual[nome].aceita_nulo
    }
    ficou_menos_restrita = {
        nome
        for nome in em_comum
        if not por_nome_anterior[nome].aceita_nulo and por_nome_atual[nome].aceita_nulo
    }

    partes_quebra = []
    if removidas:
        partes_quebra.append(f"colunas removidas: {sorted(removidas)}")
    if tipo_alterado:
        partes_quebra.append(f"tipo alterado: {sorted(tipo_alterado)}")
    if ficou_mais_restrita:
        partes_quebra.append(f"ficaram NOT NULL: {sorted(ficou_mais_restrita)}")

    if partes_quebra:
        return ClassificacaoMudancaSchema.QUEBRADORA, "; ".join(partes_quebra)

    partes_aditivas = []
    if adicionadas:
        partes_aditivas.append(f"colunas novas: {sorted(adicionadas)}")
    if ficou_menos_restrita:
        partes_aditivas.append(f"ficaram opcionais: {sorted(ficou_menos_restrita)}")

    if partes_aditivas:
        return ClassificacaoMudancaSchema.ADITIVA, "; ".join(partes_aditivas)

    return ClassificacaoMudancaSchema.SEM_MUDANCA, "sem diferença de colunas, tipos ou nulabilidade"

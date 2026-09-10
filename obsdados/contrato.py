"""Contrato declarativo por dataset: YAML validado com Pydantic, erro aponta a linha."""

import pathlib
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from obsdados.baseline import MINIMO_OBSERVACOES_BASELINE_PADRAO
from obsdados.incidente import SeveridadeRegra
from obsdados.nucleo import FRACAO_AMOSTRA_PADRAO, LIMITE_LINHAS_SEM_AMOSTRAGEM


class ContratoInvalido(Exception):
    """Erro ao carregar um contrato — a mensagem já inclui a linha do problema, quando possível."""


class ConexaoContrato(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["duckdb", "postgres"]
    db_origem: str | None = None


class RegraFrescor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coluna: str
    sla_horas: float = Field(gt=0)
    severidade: SeveridadeRegra = SeveridadeRegra.ERRO


class RegraVolume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severidade: SeveridadeRegra = SeveridadeRegra.ERRO
    minimo_observacoes_baseline: int = Field(default=MINIMO_OBSERVACOES_BASELINE_PADRAO, gt=0)
    limite_desvios_mad: float = Field(default=5.0, gt=0)


class RegraSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severidade_aditiva: SeveridadeRegra = SeveridadeRegra.AVISO
    severidade_quebradora: SeveridadeRegra = SeveridadeRegra.CRITICO


class RegraNulos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coluna: str
    limite_taxa: float = Field(ge=0, le=1)
    severidade: SeveridadeRegra = SeveridadeRegra.AVISO


class PoliticaAmostragem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limite_linhas_sem_amostragem: int = Field(default=LIMITE_LINHAS_SEM_AMOSTRAGEM, gt=0)
    fracao: float = Field(default=FRACAO_AMOSTRA_PADRAO, gt=0, le=1)


class ContratoDataset(BaseModel):
    """O que o avaliador precisa saber sobre um dataset: onde olhar e o que esperar."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dataset: str
    conexao: ConexaoContrato
    tabela: str
    frescor: RegraFrescor | None = None
    volume: RegraVolume | None = None
    schema_: RegraSchema | None = Field(default=None, alias="schema")
    nulos: list[RegraNulos] = Field(default_factory=list)
    amostragem: PoliticaAmostragem = Field(default_factory=PoliticaAmostragem)


def carregar_contrato(caminho: str) -> ContratoDataset:
    texto = pathlib.Path(caminho).read_text(encoding="utf-8")
    try:
        dados = yaml.safe_load(texto)
    except yaml.YAMLError as erro:
        local = _linha_do_erro_yaml(erro)
        raise ContratoInvalido(f"YAML malformado em '{caminho}'{local}: {erro}") from erro

    if not isinstance(dados, dict):
        tipo = type(dados).__name__
        raise ContratoInvalido(f"contrato em '{caminho}' precisa ser mapeamento YAML, não {tipo}")

    try:
        return ContratoDataset.model_validate(dados)
    except ValidationError as erro:
        raise ContratoInvalido(_formatar_erro_validacao(caminho, texto, erro)) from erro


def _linha_do_erro_yaml(erro: yaml.YAMLError) -> str:
    marca = getattr(erro, "problem_mark", None)
    return "" if marca is None else f" (linha {marca.line + 1})"


def _formatar_erro_validacao(caminho: str, texto: str, erro: ValidationError) -> str:
    no_raiz = yaml.compose(texto)
    partes = []
    for detalhe in erro.errors():
        linha = _localizar_linha(no_raiz, detalhe["loc"])
        prefixo = f"linha {linha}: " if linha is not None else ""
        campo = ".".join(str(item) for item in detalhe["loc"]) or "(raiz)"
        partes.append(f"{prefixo}{campo}: {detalhe['msg']}")
    return f"contrato inválido em '{caminho}':\n" + "\n".join(partes)


def _proximo_no(no_pai: yaml.Node, chave: object) -> yaml.Node | None:
    if isinstance(no_pai, yaml.MappingNode):
        pares: list[tuple[yaml.Node, yaml.Node]] = no_pai.value
        for chave_no, valor_no in pares:
            if chave_no.value == str(chave):
                return valor_no
        return None
    if isinstance(no_pai, yaml.SequenceNode) and isinstance(chave, int):
        return no_pai.value[chave] if 0 <= chave < len(no_pai.value) else None
    return None


def _localizar_linha(no: yaml.Node | None, caminho: tuple[object, ...]) -> int | None:
    if no is None:
        return None
    atual = no
    for chave in caminho:
        proximo = _proximo_no(atual, chave)
        if proximo is None:
            return atual.start_mark.line + 1
        atual = proximo
    return atual.start_mark.line + 1

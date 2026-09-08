"""Tipos e constantes centrais compartilhados por coletor, adapters e metric store."""

from collections.abc import Mapping
from datetime import datetime
from enum import Flag, StrEnum, auto
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, model_validator


class Capacidade(Flag):
    """Bits de capacidade que um adapter pode declarar suportar."""

    NENHUMA = 0
    CONTAGEM_LINHAS = auto()
    CONTAGEM_DISTINTOS_APROXIMADA = auto()
    QUANTIS = auto()
    LEITURA_PARTICAO = auto()
    TIMESTAMP_ULTIMA_MODIFICACAO = auto()


class TipoMetrica(StrEnum):
    """Famílias de métrica do catálogo."""

    CONTAGEM_LINHAS = "contagem_linhas"


CAPACIDADE_POR_TIPO_METRICA: Final[dict[TipoMetrica, Capacidade]] = {
    TipoMetrica.CONTAGEM_LINHAS: Capacidade.CONTAGEM_LINHAS,
}
"""Capacidade mínima que um adapter precisa declarar para que o coletor peça a métrica."""

LIMITE_LINHAS_POR_METRICA: Final[int] = 10
"""Teto de linhas que uma métrica pode buscar do backend de origem (regra de push-down)."""


class StatusResultadoMetrica(StrEnum):
    """Resultado da tentativa de coletar uma métrica."""

    OK = "ok"
    NAO_SUPORTADO = "nao_suportado"
    ERRO = "erro"


class TipoAmostragem(StrEnum):
    """De onde veio o valor de uma métrica: varredura completa ou amostra."""

    FULL_SCAN = "full_scan"
    AMOSTRA = "amostra"
    NAO_APLICAVEL = "nao_aplicavel"


class EspecificacaoMetrica(BaseModel):
    """O que o coletor pede a um adapter para calcular."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    tabela: str
    tipo_metrica: TipoMetrica
    dimensao: str | None = None
    coluna: str | None = None
    parametros: Mapping[str, object] = {}


class ResultadoMetrica(BaseModel):
    """O que um adapter devolve após calcular (ou tentar calcular) uma métrica."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    tipo_metrica: TipoMetrica
    dimensao: str | None
    status: StatusResultadoMetrica
    valor: float | None = None
    tipo_amostragem: TipoAmostragem = TipoAmostragem.NAO_APLICAVEL
    motivo_nao_suportado: str | None = None
    mensagem_erro: str | None = None
    backend: str
    linhas_buscadas: int
    duracao_segundos: float
    coletado_em: datetime

    @model_validator(mode="after")
    def _valida_consistencia_status(self) -> Self:
        if self.status == StatusResultadoMetrica.OK and self.valor is None:
            raise ValueError("status ok exige valor não nulo")
        if (
            self.status == StatusResultadoMetrica.NAO_SUPORTADO
            and not self.motivo_nao_suportado
        ):
            raise ValueError("status nao_suportado exige motivo_nao_suportado")
        if self.status == StatusResultadoMetrica.ERRO and not self.mensagem_erro:
            raise ValueError("status erro exige mensagem_erro")
        return self


class DescricaoDataset(BaseModel):
    """Metadado leve de catálogo — nunca envolve varredura de linha."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tabela: str
    schema_ou_catalogo: str | None = None
    linhas_estimadas: int | None = None


class ColunaSchema(BaseModel):
    """Uma coluna do schema de um dataset, conforme `information_schema`/`DESCRIBE`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nome: str
    tipo: str
    aceita_nulo: bool

"""Protocolo que todo backend de origem (DuckDB, SQL Server, Postgres, Delta...) implementa."""

from typing import Protocol, runtime_checkable

from obsdados.nucleo import (
    Capacidade,
    ColunaSchema,
    DescricaoDataset,
    EspecificacaoMetrica,
    ResultadoMetrica,
)


@runtime_checkable
class Adaptador(Protocol):
    """Contrato que todo backend de origem implementa."""

    nome_backend: str

    def listar_datasets(self) -> list[DescricaoDataset]:
        """Lista datasets disponíveis via metadado de catálogo (sem tocar linha de dado)."""
        ...

    def descrever_schema(self, tabela: str) -> list[ColunaSchema]:
        """Descreve colunas/tipos de uma tabela via metadado de catálogo."""
        ...

    def capacidades_suportadas(self) -> Capacidade:
        """Declara quais famílias de métrica este backend consegue calcular via push-down."""
        ...

    def executar_metrica(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        """Calcula a métrica pedida via SQL executado na origem."""
        ...

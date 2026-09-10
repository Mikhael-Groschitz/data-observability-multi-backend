"""Utilitário de SQL compartilhado entre adapters."""

_ASPA_DUPLA = '"'


def identificador_seguro(identificador: str) -> str:
    """Quota um identificador (tabela, possivelmente `schema.tabela`) para uso seguro em SQL.

    Nomes de tabela/coluna não podem ser parametrizados com `?`/`%s` — só
    valores podem. Quotar cada parte e escapar aspas embutidas evita injeção
    via identificador. Válido tanto para DuckDB quanto para Postgres, que
    seguem a mesma convenção de quoting de identificador do SQL padrão.
    """

    def _quotar_parte(parte: str) -> str:
        return _ASPA_DUPLA + parte.replace(_ASPA_DUPLA, _ASPA_DUPLA * 2) + _ASPA_DUPLA

    return ".".join(_quotar_parte(parte) for parte in identificador.split("."))

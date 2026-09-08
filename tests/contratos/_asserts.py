"""Asserção única e reaproveitável do contrato de push-down."""

from obsdados.nucleo import LIMITE_LINHAS_POR_METRICA, ResultadoMetrica


def assert_respeita_limite_pushdown(
    resultado: ResultadoMetrica, limite: int = LIMITE_LINHAS_POR_METRICA
) -> None:
    assert resultado.linhas_buscadas <= limite, (
        f"adapter '{resultado.backend}' buscou {resultado.linhas_buscadas} linhas "
        f"para {resultado.tipo_metrica} (limite: {limite}) — suspeita de fetch de dado bruto"
    )

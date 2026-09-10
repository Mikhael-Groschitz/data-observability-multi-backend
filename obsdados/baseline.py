"""Baseline estatístico: mediana móvel com MAD, agrupada por dia da semana."""

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

FATOR_ESCALA_MAD: Final[float] = 1.4826
"""Converte MAD para uma escala comparável a desvio padrão sob normalidade — convenção usual."""

MINIMO_OBSERVACOES_BASELINE_PADRAO: Final[int] = 5
"""Observações do mesmo dia da semana exigidas antes de confiar na mediana (ver README)."""


@dataclass(frozen=True)
class Baseline:
    mediana: float
    mad: float
    n_observacoes: int

    def desvio_em_mads(self, valor: float) -> float:
        mad_efetivo = self.mad if self.mad > 0 else 1e-9
        return abs(valor - self.mediana) / (mad_efetivo * FATOR_ESCALA_MAD)


def calcular_baseline(valores: Sequence[float]) -> Baseline:
    mediana = statistics.median(valores)
    mad = statistics.median(abs(v - mediana) for v in valores)
    return Baseline(mediana=mediana, mad=mad, n_observacoes=len(valores))


def baseline_por_dia_semana(
    observacoes: Sequence[tuple[datetime, float]],
) -> dict[int, Baseline]:
    """Agrupa observações por dia da semana (0=segunda) e calcula uma baseline por grupo."""
    por_dia: dict[int, list[float]] = defaultdict(list)
    for coletado_em, valor in observacoes:
        por_dia[coletado_em.weekday()].append(valor)
    return {dia: calcular_baseline(valores) for dia, valores in por_dia.items()}

"""Testa mediana+MAD, agrupamento por dia da semana e o caso de MAD zero."""

from datetime import datetime

from obsdados.baseline import baseline_por_dia_semana, calcular_baseline


def test_calcular_baseline_mediana_e_mad() -> None:
    baseline = calcular_baseline([10.0, 12.0, 11.0, 50.0, 9.0])
    assert baseline.mediana == 11.0
    assert baseline.n_observacoes == 5
    assert baseline.mad > 0


def test_desvio_em_mads_zero_quando_valor_igual_a_mediana() -> None:
    baseline = calcular_baseline([10.0, 12.0, 11.0, 9.0, 13.0])
    assert baseline.desvio_em_mads(baseline.mediana) == 0.0


def test_desvio_em_mads_nao_explode_com_historico_constante() -> None:
    baseline = calcular_baseline([100.0, 100.0, 100.0, 100.0])
    assert baseline.mad == 0.0
    assert baseline.desvio_em_mads(100.0) == 0.0
    assert baseline.desvio_em_mads(101.0) > 0.0


def test_baseline_por_dia_semana_agrupa_corretamente() -> None:
    segunda_1 = datetime(2026, 1, 5)  # segunda-feira
    segunda_2 = datetime(2026, 1, 12)
    sabado_1 = datetime(2026, 1, 10)
    observacoes = [
        (segunda_1, 1000.0),
        (segunda_2, 1010.0),
        (sabado_1, 200.0),
    ]
    baselines = baseline_por_dia_semana(observacoes)
    assert baselines[0].n_observacoes == 2  # segunda-feira = weekday 0
    assert baselines[5].n_observacoes == 1  # sábado = weekday 5
    assert baselines[0].mediana != baselines[5].mediana

"""Avalia um dataset contra o contrato: lê o metric store, nunca a origem."""

from datetime import datetime

import duckdb

from obsdados.armazenamento import consultar_historico
from obsdados.baseline import baseline_por_dia_semana
from obsdados.contrato import ContratoDataset, RegraNulos
from obsdados.incidente import (
    Incidente,
    RegraIncidente,
    SeveridadeRegra,
    consultar_incidentes_abertos,
    gravar_incidente,
    marcar_resolvido,
)
from obsdados.nucleo import (
    PARAMETRO_COLUNAS_SCHEMA,
    ColunaSchema,
    ResultadoMetrica,
    StatusResultadoMetrica,
    TipoMetrica,
)
from obsdados.schema import ClassificacaoMudancaSchema, classificar_mudanca_schema

_LIMITE_HISTORICO = 500
_MINIMO_PONTOS_COMPARACAO = 2


def avaliar_dataset(
    contrato: ContratoDataset, con_store: duckdb.DuckDBPyConnection, agora: datetime | None = None
) -> list[Incidente]:
    """Roda as regras do contrato para um dataset e devolve os incidentes novos desta rodada."""
    momento = agora or datetime.now()
    novos: list[Incidente] = []

    if contrato.frescor:
        novos += _sem_none(_avaliar_frescor(contrato, con_store, momento))
    if contrato.volume:
        novos += _sem_none(_avaliar_volume(contrato, con_store, momento))
    if contrato.schema_:
        novos += _sem_none(_avaliar_schema(contrato, con_store, momento))
    for regra_nulos in contrato.nulos:
        novos += _sem_none(_avaliar_nulos(contrato, regra_nulos, con_store, momento))

    return novos


def _sem_none(incidente: Incidente | None) -> list[Incidente]:
    return [] if incidente is None else [incidente]


def _registrar_ou_resolver(  # noqa: PLR0913
    con: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    regra: RegraIncidente,
    coluna: str | None,
    disparou: bool,
    severidade: SeveridadeRegra,
    valor_observado: str,
    valor_esperado: str,
    desvio: str,
    justificativa: str,
    agora: datetime,
) -> Incidente | None:
    abertos = consultar_incidentes_abertos(con, dataset, regra, coluna)
    if not disparou:
        for incidente in abertos:
            if incidente.id is not None:
                marcar_resolvido(con, incidente.id, agora)
        return None
    if abertos:
        return None
    incidente = Incidente(
        dataset=dataset,
        regra=regra,
        coluna=coluna,
        severidade=severidade,
        valor_observado=valor_observado,
        valor_esperado=valor_esperado,
        desvio=desvio,
        justificativa=justificativa,
        detectado_em=agora,
    )
    gravar_incidente(con, incidente)
    return incidente


def _avaliar_frescor(
    contrato: ContratoDataset, con: duckdb.DuckDBPyConnection, agora: datetime
) -> Incidente | None:
    regra = contrato.frescor
    if regra is None:
        return None
    historico = consultar_historico(
        con, contrato.dataset, tipo_metrica=TipoMetrica.FRESCOR, coluna=regra.coluna, limite=1
    )
    if not historico or historico[0].status != StatusResultadoMetrica.OK:
        return None
    if historico[0].valor is None:
        return None

    lag_segundos = historico[0].valor
    limite_segundos = regra.sla_horas * 3600
    disparou = lag_segundos > limite_segundos
    return _registrar_ou_resolver(
        con,
        dataset=contrato.dataset,
        regra=RegraIncidente.FRESCOR,
        coluna=regra.coluna,
        disparou=disparou,
        severidade=regra.severidade,
        valor_observado=f"{lag_segundos / 3600:.2f} h sem atualizar",
        valor_esperado=f"até {regra.sla_horas:.2f} h (SLA do contrato)",
        desvio=f"{(lag_segundos - limite_segundos) / 3600:.2f} h acima do SLA",
        justificativa=(
            f"coluna '{regra.coluna}' de '{contrato.dataset}' está há {lag_segundos / 3600:.2f} h "
            f"sem dado novo — SLA do contrato é {regra.sla_horas:.2f} h"
        ),
        agora=agora,
    )


def _avaliar_volume(
    contrato: ContratoDataset, con: duckdb.DuckDBPyConnection, agora: datetime
) -> Incidente | None:
    regra = contrato.volume
    if regra is None:
        return None
    historico = consultar_historico(
        con, contrato.dataset, tipo_metrica=TipoMetrica.CONTAGEM_LINHAS, limite=_LIMITE_HISTORICO
    )
    totais = [r for r in historico if r.dimensao is None and r.status == StatusResultadoMetrica.OK]
    if len(totais) < _MINIMO_PONTOS_COMPARACAO:
        return None

    atual, anteriores = totais[0], totais[1:]
    observacoes = [(r.coletado_em, r.valor) for r in anteriores if r.valor is not None]
    baselines = baseline_por_dia_semana(observacoes)
    baseline_do_dia = baselines.get(atual.coletado_em.weekday())
    if baseline_do_dia is None or baseline_do_dia.n_observacoes < regra.minimo_observacoes_baseline:
        return None
    if atual.valor is None:
        return None

    desvio_mads = baseline_do_dia.desvio_em_mads(atual.valor)
    disparou = desvio_mads > regra.limite_desvios_mad
    dia_semana = atual.coletado_em.strftime("%A")
    return _registrar_ou_resolver(
        con,
        dataset=contrato.dataset,
        regra=RegraIncidente.VOLUME,
        coluna=None,
        disparou=disparou,
        severidade=regra.severidade,
        valor_observado=f"{atual.valor:.0f} linhas",
        valor_esperado=(
            f"{baseline_do_dia.mediana:.0f} linhas (mediana de {baseline_do_dia.n_observacoes} "
            f"observações de {dia_semana})"
        ),
        desvio=f"{desvio_mads:.1f} MADs (limite: {regra.limite_desvios_mad:.1f})",
        justificativa=(
            f"'{contrato.dataset}' coletou {atual.valor:.0f} linhas nesta {dia_semana}, "
            f"contra uma mediana histórica de {baseline_do_dia.mediana:.0f} para o mesmo dia da "
            f"semana — desvio de {desvio_mads:.1f} MADs, acima do limite de "
            f"{regra.limite_desvios_mad:.1f}"
        ),
        agora=agora,
    )


def _avaliar_schema(
    contrato: ContratoDataset, con: duckdb.DuckDBPyConnection, agora: datetime
) -> Incidente | None:
    regra = contrato.schema_
    if regra is None:
        return None
    historico = consultar_historico(
        con, contrato.dataset, tipo_metrica=TipoMetrica.SCHEMA_HASH, limite=2
    )
    ok = [
        r for r in historico if r.status == StatusResultadoMetrica.OK and r.valor_texto is not None
    ]
    if len(ok) < _MINIMO_PONTOS_COMPARACAO:
        return None

    atual, anterior = ok[0], ok[1]
    if atual.valor_texto == anterior.valor_texto:
        return _registrar_ou_resolver(
            con,
            dataset=contrato.dataset,
            regra=RegraIncidente.SCHEMA,
            coluna=None,
            disparou=False,
            severidade=regra.severidade_aditiva,
            valor_observado="",
            valor_esperado="",
            desvio="",
            justificativa="",
            agora=agora,
        )

    colunas_anterior = _colunas_do_resultado(anterior)
    colunas_atual = _colunas_do_resultado(atual)
    if colunas_anterior is None or colunas_atual is None:
        return None
    if atual.valor_texto is None or anterior.valor_texto is None:
        return None

    classificacao, motivo = classificar_mudanca_schema(colunas_anterior, colunas_atual)
    severidade = (
        regra.severidade_quebradora
        if classificacao == ClassificacaoMudancaSchema.QUEBRADORA
        else regra.severidade_aditiva
    )
    return _registrar_ou_resolver(
        con,
        dataset=contrato.dataset,
        regra=RegraIncidente.SCHEMA,
        coluna=None,
        disparou=True,
        severidade=severidade,
        valor_observado=f"hash {atual.valor_texto[:12]}...",
        valor_esperado=f"hash {anterior.valor_texto[:12]}...",
        desvio=classificacao.value,
        justificativa=f"schema de '{contrato.dataset}' mudou ({classificacao.value}): {motivo}",
        agora=agora,
    )


def _colunas_do_resultado(resultado: ResultadoMetrica) -> list[ColunaSchema] | None:
    brutas = resultado.parametros.get(PARAMETRO_COLUNAS_SCHEMA)
    if not isinstance(brutas, list):
        return None
    return [ColunaSchema(**c) for c in brutas]


def _avaliar_nulos(
    contrato: ContratoDataset, regra: RegraNulos, con: duckdb.DuckDBPyConnection, agora: datetime
) -> Incidente | None:
    historico = consultar_historico(
        con, contrato.dataset, tipo_metrica=TipoMetrica.TAXA_NULOS, coluna=regra.coluna, limite=1
    )
    if not historico or historico[0].status != StatusResultadoMetrica.OK:
        return None
    if historico[0].valor is None:
        return None

    taxa = historico[0].valor
    disparou = taxa > regra.limite_taxa
    return _registrar_ou_resolver(
        con,
        dataset=contrato.dataset,
        regra=RegraIncidente.NULOS,
        coluna=regra.coluna,
        disparou=disparou,
        severidade=regra.severidade,
        valor_observado=f"{taxa:.1%} de nulos",
        valor_esperado=f"até {regra.limite_taxa:.1%} (limite do contrato)",
        desvio=f"{(taxa - regra.limite_taxa):.1%} acima do limite",
        justificativa=(
            f"coluna '{regra.coluna}' de '{contrato.dataset}' tem {taxa:.1%} de nulos, "
            f"acima do limite de {regra.limite_taxa:.1%} declarado no contrato"
        ),
        agora=agora,
    )

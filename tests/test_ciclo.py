"""Testa o ciclo completo: coleta o que o contrato pede, avalia e notifica."""

from pathlib import Path

import duckdb

from obsdados.alerta import TipoWebhook
from obsdados.armazenamento import consultar_historico
from obsdados.ciclo import executar_ciclo, montar_especificacoes
from obsdados.contrato import ConexaoContrato, ContratoDataset, RegraFrescor, RegraSchema
from obsdados.db import conectar_escrita
from obsdados.nucleo import TipoMetrica
from tests.conftest import ServidorWebhook


def _preparar_origem(tmp_path: Path) -> str:
    caminho = str(tmp_path / "origem.duckdb")
    con = duckdb.connect(caminho)
    con.execute("CREATE TABLE pedidos (id INTEGER, criado_em TIMESTAMP)")
    con.execute("INSERT INTO pedidos SELECT i, now() FROM range(20) AS t(i)")
    con.close()
    return caminho


def _contrato(origem: str) -> ContratoDataset:
    return ContratoDataset(
        dataset="teste.pedidos",
        conexao=ConexaoContrato(backend="duckdb", db_origem=origem),
        tabela="pedidos",
        frescor=RegraFrescor(coluna="criado_em", sla_horas=24),
        schema_=RegraSchema(),
    )


def test_montar_especificacoes_reflete_as_regras_do_contrato(tmp_path: Path) -> None:
    contrato = _contrato(_preparar_origem(tmp_path))

    especificacoes = montar_especificacoes(contrato)

    tipos = {e.tipo_metrica for e in especificacoes}
    assert tipos == {TipoMetrica.FRESCOR, TipoMetrica.SCHEMA_HASH}


def test_executar_ciclo_coleta_e_grava_no_store(tmp_path: Path) -> None:
    origem = _preparar_origem(tmp_path)
    contrato = _contrato(origem)
    store = str(tmp_path / "metricas.duckdb")
    con = conectar_escrita(store)

    executar_ciclo(contrato, con, webhook_url=None, webhook_tipo=TipoWebhook.DISCORD)

    historico_frescor = consultar_historico(
        con, contrato.dataset, tipo_metrica=TipoMetrica.FRESCOR
    )
    historico_schema = consultar_historico(
        con, contrato.dataset, tipo_metrica=TipoMetrica.SCHEMA_HASH
    )
    assert len(historico_frescor) == 1
    assert len(historico_schema) == 1


def test_executar_ciclo_notifica_incidente_no_webhook(
    tmp_path: Path, servidor_webhook: ServidorWebhook
) -> None:
    origem = str(tmp_path / "origem.duckdb")
    con_origem = duckdb.connect(origem)
    con_origem.execute("CREATE TABLE pedidos (id INTEGER, criado_em TIMESTAMP)")
    con_origem.execute(
        "INSERT INTO pedidos SELECT i, now() - INTERVAL 30 HOUR FROM range(20) AS t(i)"
    )
    con_origem.close()
    contrato = _contrato(origem)
    store = str(tmp_path / "metricas.duckdb")
    con = conectar_escrita(store)

    resultado = executar_ciclo(
        contrato, con, webhook_url=servidor_webhook.url, webhook_tipo=TipoWebhook.DISCORD
    )

    assert len(resultado.abertos) == 1
    assert resultado.abertos[0].regra.value == "frescor"
    assert len(servidor_webhook.requisicoes) == 1
    assert "frescor" in servidor_webhook.requisicoes[0]["content"]

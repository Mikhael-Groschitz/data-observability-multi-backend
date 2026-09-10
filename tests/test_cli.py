"""Testa a CLI ponta a ponta: `coletar` grava no store, `historico` lê e imprime."""

import json
from pathlib import Path

import duckdb
import pytest

from obsdados.cli import main


def _preparar_banco_origem(tmp_path: Path) -> str:
    caminho = str(tmp_path / "origem.duckdb")
    con = duckdb.connect(caminho)
    con.execute("CREATE TABLE pedidos AS SELECT * FROM range(9) AS t(id)")
    con.close()
    return caminho


def test_coletar_e_historico_ponta_a_ponta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origem = _preparar_banco_origem(tmp_path)
    store = str(tmp_path / "metricas.duckdb")

    codigo = main(
        [
            "coletar",
            "--backend",
            "duckdb",
            "--db-origem",
            origem,
            "--tabela",
            "pedidos",
            "--dataset",
            "teste.pedidos",
            "--tipo-metrica",
            "contagem_linhas",
            "--store",
            store,
        ]
    )
    assert codigo == 0
    saida_coleta = json.loads(capsys.readouterr().out)
    assert saida_coleta["status"] == "ok"
    assert saida_coleta["valor"] == 9.0

    codigo = main(["historico", "--store", store, "--dataset", "teste.pedidos"])
    assert codigo == 0
    saida_historico = capsys.readouterr().out
    assert "contagem_linhas" in saida_historico
    assert "ok" in saida_historico


def test_coletar_maximo_exige_permite_valor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origem = _preparar_banco_origem(tmp_path)
    store = str(tmp_path / "metricas.duckdb")

    codigo = main(
        [
            "coletar",
            "--backend", "duckdb",
            "--db-origem", origem,
            "--tabela", "pedidos",
            "--dataset", "teste.pedidos",
            "--tipo-metrica", "maximo",
            "--coluna", "id",
            "--store", store,
        ]
    )
    assert codigo == 0
    bloqueado = json.loads(capsys.readouterr().out)
    assert bloqueado["status"] == "nao_suportado"

    codigo = main(
        [
            "coletar",
            "--backend", "duckdb",
            "--db-origem", origem,
            "--tabela", "pedidos",
            "--dataset", "teste.pedidos",
            "--tipo-metrica", "maximo",
            "--coluna", "id",
            "--permite-valor",
            "--store", store,
        ]
    )
    assert codigo == 0
    liberado = json.loads(capsys.readouterr().out)
    assert liberado["status"] == "ok"
    assert liberado["valor_texto"] == "8"

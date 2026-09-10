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


def test_avaliar_sem_incidente_quando_tudo_dentro_do_esperado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origem = str(tmp_path / "origem.duckdb")
    con = duckdb.connect(origem)
    con.execute("CREATE TABLE pedidos (id INTEGER, criado_em TIMESTAMP)")
    con.execute("INSERT INTO pedidos SELECT i, now() FROM range(50) AS t(i)")
    con.close()
    store = str(tmp_path / "metricas.duckdb")

    main(
        [
            "coletar",
            "--backend", "duckdb",
            "--db-origem", origem,
            "--tabela", "pedidos",
            "--dataset", "teste.pedidos",
            "--tipo-metrica", "frescor",
            "--coluna", "criado_em",
            "--store", store,
        ]
    )
    capsys.readouterr()

    contrato_caminho = tmp_path / "contrato.yaml"
    contrato_caminho.write_text(
        f"""
dataset: teste.pedidos
conexao:
  backend: duckdb
  db_origem: {origem}
tabela: pedidos
frescor:
  coluna: criado_em
  sla_horas: 24
""",
        encoding="utf-8",
    )

    codigo = main(["avaliar", "--contrato", str(contrato_caminho), "--store", store])

    assert codigo == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida["incidentes"] == []


def test_avaliar_contrato_malformado_mostra_linha(tmp_path: Path) -> None:
    store = str(tmp_path / "metricas.duckdb")
    contrato_caminho = tmp_path / "contrato.yaml"
    contrato_caminho.write_text("dataset: ds\nconexao:\n  backend: duckdb\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["avaliar", "--contrato", str(contrato_caminho), "--store", store])

    assert "tabela" in str(excinfo.value)

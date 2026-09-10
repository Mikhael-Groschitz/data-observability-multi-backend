"""Testa o loop do agendador: quantos ciclos roda, quando dorme, o que ele reporta.

`dormir` é injetável — nada aqui espera tempo de parede real.
"""

from pathlib import Path

import duckdb

from obsdados.agendador import executar_agendador
from obsdados.alerta import TipoWebhook
from obsdados.avaliador import ResultadoAvaliacao


def _preparar_contrato(tmp_path: Path, nome: str) -> Path:
    origem = tmp_path / f"{nome}.duckdb"
    con = duckdb.connect(str(origem))
    con.execute("CREATE TABLE pedidos (id INTEGER, criado_em TIMESTAMP)")
    con.execute("INSERT INTO pedidos SELECT i, now() FROM range(10) AS t(i)")
    con.close()

    caminho_contrato = tmp_path / f"{nome}.yaml"
    caminho_contrato.write_text(
        f"""
dataset: {nome}
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
    return caminho_contrato


def test_agendador_roda_o_numero_de_ciclos_pedido(tmp_path: Path) -> None:
    contrato = _preparar_contrato(tmp_path, "ds_a")
    store = str(tmp_path / "metricas.duckdb")
    esperas: list[float] = []
    avaliacoes: list[tuple[str, ResultadoAvaliacao]] = []

    executar_agendador(
        [contrato],
        store,
        webhook_url=None,
        webhook_tipo=TipoWebhook.DISCORD,
        intervalo_segundos=5.0,
        ciclos=3,
        dormir=esperas.append,
        ao_avaliar=lambda dataset, resultado: avaliacoes.append((dataset, resultado)),
    )

    assert len(avaliacoes) == 3
    assert esperas == [5.0, 5.0]  # dorme entre ciclos, não depois do último


def test_agendador_roda_todos_os_contratos_do_diretorio(tmp_path: Path) -> None:
    contrato_a = _preparar_contrato(tmp_path, "ds_a")
    contrato_b = _preparar_contrato(tmp_path, "ds_b")
    store = str(tmp_path / "metricas.duckdb")
    avaliacoes: list[tuple[str, ResultadoAvaliacao]] = []

    executar_agendador(
        [contrato_a, contrato_b],
        store,
        webhook_url=None,
        webhook_tipo=TipoWebhook.DISCORD,
        intervalo_segundos=5.0,
        ciclos=1,
        dormir=lambda _: None,
        ao_avaliar=lambda dataset, resultado: avaliacoes.append((dataset, resultado)),
    )

    datasets_avaliados = {dataset for dataset, _ in avaliacoes}
    assert datasets_avaliados == {"ds_a", "ds_b"}


def test_agendador_ignora_contrato_invalido_e_continua(tmp_path: Path) -> None:
    contrato_valido = _preparar_contrato(tmp_path, "ds_a")
    contrato_invalido = tmp_path / "invalido.yaml"
    contrato_invalido.write_text("dataset: ds_invalido\n", encoding="utf-8")
    store = str(tmp_path / "metricas.duckdb")
    avaliacoes: list[tuple[str, ResultadoAvaliacao]] = []

    executar_agendador(
        [contrato_invalido, contrato_valido],
        store,
        webhook_url=None,
        webhook_tipo=TipoWebhook.DISCORD,
        intervalo_segundos=5.0,
        ciclos=1,
        dormir=lambda _: None,
        ao_avaliar=lambda dataset, resultado: avaliacoes.append((dataset, resultado)),
    )

    assert [dataset for dataset, _ in avaliacoes] == ["ds_a"]

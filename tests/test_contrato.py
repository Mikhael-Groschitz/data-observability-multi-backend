"""Testa o carregamento do contrato: caso válido e os dois jeitos de dar errado."""

from pathlib import Path

import pytest

from obsdados.contrato import ContratoInvalido, carregar_contrato
from obsdados.incidente import SeveridadeRegra


def test_carrega_contrato_valido(tmp_path: Path) -> None:
    caminho = tmp_path / "contrato.yaml"
    caminho.write_text(
        """
dataset: vendas.pedidos
conexao:
  backend: duckdb
  db_origem: origem.duckdb
tabela: vendas.pedidos
frescor:
  coluna: criado_em
  sla_horas: 24
volume:
  severidade: critico
nulos:
  - coluna: valor
    limite_taxa: 0.05
""",
        encoding="utf-8",
    )

    contrato = carregar_contrato(str(caminho))

    assert contrato.dataset == "vendas.pedidos"
    assert contrato.conexao.backend == "duckdb"
    assert contrato.frescor is not None
    assert contrato.frescor.sla_horas == 24
    assert contrato.frescor.severidade == SeveridadeRegra.ERRO  # default
    assert contrato.volume is not None
    assert contrato.volume.severidade == SeveridadeRegra.CRITICO
    assert len(contrato.nulos) == 1
    assert contrato.nulos[0].coluna == "valor"


def test_yaml_malformado_aponta_linha(tmp_path: Path) -> None:
    caminho = tmp_path / "contrato.yaml"
    caminho.write_text(
        "dataset: vendas.pedidos\nconexao:\n  backend: duckdb\n  db_origem: [origem.duckdb\n",
        encoding="utf-8",
    )

    with pytest.raises(ContratoInvalido) as excinfo:
        carregar_contrato(str(caminho))

    assert "linha" in str(excinfo.value)


def test_campo_obrigatorio_ausente_aponta_erro_claro(tmp_path: Path) -> None:
    caminho = tmp_path / "contrato.yaml"
    caminho.write_text(
        """
dataset: vendas.pedidos
conexao:
  backend: duckdb
tabela: vendas.pedidos
frescor:
  sla_horas: 24
""",
        encoding="utf-8",
    )

    with pytest.raises(ContratoInvalido) as excinfo:
        carregar_contrato(str(caminho))

    mensagem = str(excinfo.value)
    assert "frescor" in mensagem
    assert "coluna" in mensagem


def test_campo_desconhecido_e_rejeitado(tmp_path: Path) -> None:
    caminho = tmp_path / "contrato.yaml"
    caminho.write_text(
        """
dataset: vendas.pedidos
conexao:
  backend: duckdb
tabela: vendas.pedidos
campo_que_nao_existe: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ContratoInvalido):
        carregar_contrato(str(caminho))


def test_amostragem_usa_padroes_do_nucleo_quando_omitida(tmp_path: Path) -> None:
    caminho = tmp_path / "contrato.yaml"
    caminho.write_text(
        "dataset: ds\nconexao:\n  backend: duckdb\ntabela: t\n",
        encoding="utf-8",
    )

    contrato = carregar_contrato(str(caminho))

    assert contrato.amostragem.limite_linhas_sem_amostragem == 100_000
    assert 0 < contrato.amostragem.fracao <= 1

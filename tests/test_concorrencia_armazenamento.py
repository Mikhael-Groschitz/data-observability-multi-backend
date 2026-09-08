"""Prova, com processos reais e `multiprocessing.Event`, a concorrência do metric store."""

import multiprocessing
import multiprocessing.synchronize
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from obsdados.armazenamento import consultar_historico
from obsdados.db import conectar_escrita, conectar_leitura, gravar_e_fechar
from obsdados.nucleo import ResultadoMetrica, StatusResultadoMetrica, TipoAmostragem, TipoMetrica

_CONTEXTO = multiprocessing.get_context("spawn")


def _processo_escritor_aguarda(
    caminho: str,
    evento_conectado: multiprocessing.synchronize.Event,
    evento_pode_fechar: multiprocessing.synchronize.Event,
) -> None:
    con = conectar_escrita(caminho)
    evento_conectado.set()
    evento_pode_fechar.wait(timeout=5)
    con.close()


def _processo_escritor_grava_e_fecha(
    caminho: str, evento_gravou: multiprocessing.synchronize.Event
) -> None:
    con = conectar_escrita(caminho)
    resultado = ResultadoMetrica(
        dataset="ds",
        tipo_metrica=TipoMetrica.CONTAGEM_LINHAS,
        dimensao=None,
        status=StatusResultadoMetrica.OK,
        valor=42.0,
        tipo_amostragem=TipoAmostragem.FULL_SCAN,
        backend="duckdb",
        linhas_buscadas=1,
        duracao_segundos=0.001,
        coletado_em=datetime.now(),
    )
    gravar_e_fechar(con, resultado)
    evento_gravou.set()


def test_leitor_falha_com_lock_enquanto_escritor_ativo(tmp_path: Path) -> None:
    caminho = str(tmp_path / "metricas.duckdb")
    evento_conectado = _CONTEXTO.Event()
    evento_pode_fechar = _CONTEXTO.Event()
    processo = _CONTEXTO.Process(
        target=_processo_escritor_aguarda, args=(caminho, evento_conectado, evento_pode_fechar)
    )
    processo.start()
    try:
        assert evento_conectado.wait(timeout=5), "escritor não conectou a tempo"
        with pytest.raises(duckdb.Error):
            duckdb.connect(caminho, read_only=True)
    finally:
        evento_pode_fechar.set()
        processo.join(timeout=5)
    assert processo.exitcode == 0


def test_leitor_ve_dado_apos_escritor_fechar_com_retry(tmp_path: Path) -> None:
    caminho = str(tmp_path / "metricas.duckdb")
    evento_gravou = _CONTEXTO.Event()
    processo = _CONTEXTO.Process(
        target=_processo_escritor_grava_e_fecha, args=(caminho, evento_gravou)
    )
    processo.start()
    try:
        assert evento_gravou.wait(timeout=5), "escritor não gravou a tempo"
        processo.join(timeout=5)

        con = conectar_leitura(caminho, tentativas=10, espera_base_segundos=0.02)
        try:
            historico = consultar_historico(con, "ds")
        finally:
            con.close()

        assert len(historico) == 1
        assert historico[0].valor == 42.0
    finally:
        if processo.is_alive():
            processo.terminate()

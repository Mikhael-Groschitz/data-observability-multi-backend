"""Interface de linha de comando: coletar uma métrica e ler o histórico."""

import argparse
import json
import os
from collections.abc import Sequence

import duckdb

from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.armazenamento import consultar_historico
from obsdados.coletor import coletar_metrica
from obsdados.db import conectar_escrita, conectar_leitura, gravar_e_fechar
from obsdados.logging_config import configurar_logging
from obsdados.nucleo import (
    EspecificacaoMetrica,
    ResultadoMetrica,
    StatusResultadoMetrica,
    TipoMetrica,
)


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="obsdados")
    subparsers = parser.add_subparsers(dest="comando")

    coletar = subparsers.add_parser(
        "coletar", help="coleta uma métrica de um dataset e grava no metric store"
    )
    coletar.add_argument("--backend", choices=["duckdb"], default="duckdb")
    coletar.add_argument("--db-origem", required=True, help="caminho do banco DuckDB observado")
    coletar.add_argument("--tabela", required=True, help="tabela (ou schema.tabela) a medir")
    coletar.add_argument("--dataset", required=True, help="identificador lógico do dataset")
    coletar.add_argument("--tipo-metrica", choices=[m.value for m in TipoMetrica], required=True)
    coletar.add_argument("--store", default=os.environ.get("OBSDADOS_METRIC_STORE_PATH"))
    coletar.set_defaults(func=_comando_coletar)

    historico = subparsers.add_parser("historico", help="lê o histórico de métricas de um dataset")
    historico.add_argument("--store", default=os.environ.get("OBSDADOS_METRIC_STORE_PATH"))
    historico.add_argument("--dataset", required=True)
    historico.add_argument("--limite", type=int, default=20)
    historico.set_defaults(func=_comando_historico)

    return parser


def _comando_coletar(args: argparse.Namespace) -> int:
    if not args.store:
        raise SystemExit("--store é obrigatório (ou defina OBSDADOS_METRIC_STORE_PATH)")

    con_origem = duckdb.connect(args.db_origem, read_only=True)
    try:
        adaptador = AdaptadorDuckDB(con_origem)
        especificacao = EspecificacaoMetrica(
            dataset=args.dataset,
            tabela=args.tabela,
            tipo_metrica=TipoMetrica(args.tipo_metrica),
        )
        resultado = coletar_metrica(adaptador, especificacao)
    finally:
        con_origem.close()

    con_store = conectar_escrita(args.store)
    gravar_e_fechar(con_store, resultado)

    saida = {
        "status": resultado.status.value,
        "valor": resultado.valor,
        "linhas_buscadas": resultado.linhas_buscadas,
        "duracao_segundos": resultado.duracao_segundos,
    }
    print(json.dumps(saida, ensure_ascii=False))
    return 1 if resultado.status == StatusResultadoMetrica.ERRO else 0


def _comando_historico(args: argparse.Namespace) -> int:
    if not args.store:
        raise SystemExit("--store é obrigatório (ou defina OBSDADOS_METRIC_STORE_PATH)")

    con = conectar_leitura(args.store)
    try:
        historico = consultar_historico(con, args.dataset, limite=args.limite)
    finally:
        con.close()

    print(_formatar_tabela(historico))
    return 0


def _formatar_tabela(historico: Sequence[ResultadoMetrica]) -> str:
    cabecalhos = [
        "coletado_em",
        "tipo_metrica",
        "status",
        "valor",
        "backend",
        "linhas_buscadas",
        "duracao_s",
    ]
    linhas = [
        [
            resultado.coletado_em.isoformat(sep=" ", timespec="seconds"),
            resultado.tipo_metrica.value,
            resultado.status.value,
            "" if resultado.valor is None else str(resultado.valor),
            resultado.backend,
            str(resultado.linhas_buscadas),
            f"{resultado.duracao_segundos:.4f}",
        ]
        for resultado in historico
    ]
    def _largura_coluna(i: int) -> int:
        maior_valor = max((len(linha[i]) for linha in linhas), default=0)
        return max(len(cabecalhos[i]), maior_valor)

    larguras = [_largura_coluna(i) for i in range(len(cabecalhos))]

    def _formatar_linha(celulas: Sequence[str]) -> str:
        pares = zip(celulas, larguras, strict=True)
        return "  ".join(celula.ljust(largura) for celula, largura in pares)

    separador = _formatar_linha(["-" * largura for largura in larguras])
    linhas_formatadas = [_formatar_linha(cabecalhos), separador]
    linhas_formatadas.extend(_formatar_linha(linha) for linha in linhas)
    return "\n".join(linhas_formatadas)


def main(argv: Sequence[str] | None = None) -> int:
    configurar_logging()
    parser = _construir_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    resultado: int = args.func(args)
    return resultado

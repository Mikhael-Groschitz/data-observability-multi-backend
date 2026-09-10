"""Interface de linha de comando: coletar uma métrica e ler o histórico."""

import argparse
import json
import os
from collections.abc import Callable, Sequence
from typing import Any

import duckdb
import psycopg

from obsdados.adaptador import Adaptador
from obsdados.adaptadores.adaptador_duckdb import AdaptadorDuckDB
from obsdados.adaptadores.adaptador_postgres import AdaptadorPostgres
from obsdados.armazenamento import consultar_historico
from obsdados.coletor import coletar_metrica
from obsdados.db import conectar_escrita, conectar_leitura, gravar_e_fechar
from obsdados.logging_config import configurar_logging
from obsdados.nucleo import (
    GRANULARIDADE_DIA,
    PARAMETRO_GRANULARIDADE,
    PARAMETRO_PERMITE_VALOR,
    PARAMETRO_QUANTIL,
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
    coletar.add_argument(
        "--backend",
        choices=["duckdb", "postgres"],
        default=os.environ.get("OBSDADOS_BACKEND_PADRAO", "duckdb"),
    )
    coletar.add_argument("--db-origem", help="caminho do banco DuckDB observado (backend duckdb)")
    coletar.add_argument("--tabela", required=True, help="tabela (ou schema.tabela) a medir")
    coletar.add_argument("--dataset", required=True, help="identificador lógico do dataset")
    coletar.add_argument("--tipo-metrica", choices=[m.value for m in TipoMetrica], required=True)
    coletar.add_argument("--coluna", help="coluna alvo da métrica, quando aplicável")
    coletar.add_argument("--dimensao", help="valor de partição ou dia para contagem por dimensão")
    coletar.add_argument(
        "--granularidade", choices=[GRANULARIDADE_DIA], help="trata --dimensao como dia"
    )
    coletar.add_argument("--quantil", type=float, help="quantil entre 0 e 1, para tipo quantil")
    coletar.add_argument(
        "--permite-valor",
        action="store_true",
        help="autoriza mínimo/máximo/quantil a materializar o valor real da coluna",
    )
    coletar.add_argument("--store", default=os.environ.get("OBSDADOS_METRIC_STORE_PATH"))
    coletar.set_defaults(func=_comando_coletar)

    historico = subparsers.add_parser("historico", help="lê o histórico de métricas de um dataset")
    historico.add_argument("--store", default=os.environ.get("OBSDADOS_METRIC_STORE_PATH"))
    historico.add_argument("--dataset", required=True)
    historico.add_argument("--coluna", help="filtra o histórico por coluna")
    historico.add_argument("--limite", type=int, default=20)
    historico.set_defaults(func=_comando_historico)

    return parser


def _conectar_postgres() -> "psycopg.Connection[Any]":
    variaveis_obrigatorias = (
        "OBSDADOS_POSTGRES_HOST",
        "OBSDADOS_POSTGRES_BANCO",
        "OBSDADOS_POSTGRES_USUARIO",
    )
    faltantes = [nome for nome in variaveis_obrigatorias if not os.environ.get(nome)]
    if faltantes:
        raise SystemExit(f"variáveis de ambiente obrigatórias ausentes: {', '.join(faltantes)}")
    return psycopg.connect(
        host=os.environ["OBSDADOS_POSTGRES_HOST"],
        port=int(os.environ.get("OBSDADOS_POSTGRES_PORTA", "5432")),
        dbname=os.environ["OBSDADOS_POSTGRES_BANCO"],
        user=os.environ["OBSDADOS_POSTGRES_USUARIO"],
        password=os.environ.get("OBSDADOS_POSTGRES_SENHA", ""),
    )


def _conectar_adaptador(args: argparse.Namespace) -> tuple[Adaptador, Callable[[], None]]:
    if args.backend == "duckdb":
        if not args.db_origem:
            raise SystemExit("--db-origem é obrigatório para --backend duckdb")
        con = duckdb.connect(args.db_origem, read_only=True)
        return AdaptadorDuckDB(con), con.close
    if args.backend == "postgres":
        con_pg = _conectar_postgres()
        return AdaptadorPostgres(con_pg), con_pg.close
    raise SystemExit(f"backend desconhecido: {args.backend}")


def _montar_parametros(args: argparse.Namespace) -> dict[str, object]:
    parametros: dict[str, object] = {}
    if args.granularidade:
        parametros[PARAMETRO_GRANULARIDADE] = args.granularidade
    if args.quantil is not None:
        parametros[PARAMETRO_QUANTIL] = args.quantil
    if args.permite_valor:
        parametros[PARAMETRO_PERMITE_VALOR] = True
    return parametros


def _comando_coletar(args: argparse.Namespace) -> int:
    if not args.store:
        raise SystemExit("--store é obrigatório (ou defina OBSDADOS_METRIC_STORE_PATH)")

    adaptador, fechar_origem = _conectar_adaptador(args)
    try:
        especificacao = EspecificacaoMetrica(
            dataset=args.dataset,
            tabela=args.tabela,
            tipo_metrica=TipoMetrica(args.tipo_metrica),
            dimensao=args.dimensao,
            coluna=args.coluna,
            parametros=_montar_parametros(args),
        )
        resultado = coletar_metrica(adaptador, especificacao)
    finally:
        fechar_origem()

    con_store = conectar_escrita(args.store)
    gravar_e_fechar(con_store, resultado)

    saida = {
        "status": resultado.status.value,
        "valor": resultado.valor,
        "valor_texto": resultado.valor_texto,
        "linhas_buscadas": resultado.linhas_buscadas,
        "duracao_segundos": resultado.duracao_segundos,
        "motivo_nao_suportado": resultado.motivo_nao_suportado,
        "mensagem_erro": resultado.mensagem_erro,
    }
    print(json.dumps(saida, ensure_ascii=False))
    return 1 if resultado.status == StatusResultadoMetrica.ERRO else 0


def _comando_historico(args: argparse.Namespace) -> int:
    if not args.store:
        raise SystemExit("--store é obrigatório (ou defina OBSDADOS_METRIC_STORE_PATH)")

    con = conectar_leitura(args.store)
    try:
        historico = consultar_historico(con, args.dataset, coluna=args.coluna, limite=args.limite)
    finally:
        con.close()

    print(_formatar_tabela(historico))
    return 0


def _formatar_tabela(historico: Sequence[ResultadoMetrica]) -> str:
    cabecalhos = [
        "coletado_em",
        "tipo_metrica",
        "coluna",
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
            resultado.coluna or "",
            resultado.status.value,
            resultado.valor_texto if resultado.valor_texto is not None else _texto_valor(resultado),
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


def _texto_valor(resultado: ResultadoMetrica) -> str:
    return "" if resultado.valor is None else str(resultado.valor)


def main(argv: Sequence[str] | None = None) -> int:
    configurar_logging()
    parser = _construir_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    resultado: int = args.func(args)
    return resultado

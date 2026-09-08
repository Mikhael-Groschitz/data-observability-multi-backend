"""Adapter de referência: lê datasets DuckDB via SQL empurrado para a própria conexão."""

import time
from datetime import datetime

import duckdb

from obsdados.instrumentacao import ConexaoInstrumentadaDuckDB
from obsdados.nucleo import (
    CAPACIDADE_POR_TIPO_METRICA,
    Capacidade,
    ColunaSchema,
    DescricaoDataset,
    EspecificacaoMetrica,
    ResultadoMetrica,
    StatusResultadoMetrica,
    TipoAmostragem,
    TipoMetrica,
)

_ASPA_DUPLA = '"'


def _identificador_seguro(identificador: str) -> str:
    """Quota um identificador (tabela, possivelmente `schema.tabela`) para uso seguro em SQL.

    Nomes de tabela não podem ser parametrizados com `?`, então cada parte é
    quotada e aspas embutidas são escapadas para evitar injeção.
    """

    def _quotar_parte(parte: str) -> str:
        return _ASPA_DUPLA + parte.replace(_ASPA_DUPLA, _ASPA_DUPLA * 2) + _ASPA_DUPLA

    return ".".join(_quotar_parte(parte) for parte in identificador.split("."))


class AdaptadorDuckDB:
    """Adapter para bancos DuckDB locais."""

    nome_backend = "duckdb"

    def __init__(self, conexao: duckdb.DuckDBPyConnection) -> None:
        self._conexao = conexao

    def listar_datasets(self) -> list[DescricaoDataset]:
        linhas = self._conexao.execute(
            "SELECT schema_name, table_name, estimated_size FROM duckdb_tables()"
        ).fetchall()
        return [
            DescricaoDataset(tabela=nome, schema_ou_catalogo=schema, linhas_estimadas=estimado)
            for schema, nome, estimado in linhas
        ]

    def descrever_schema(self, tabela: str) -> list[ColunaSchema]:
        sql = f"DESCRIBE {_identificador_seguro(tabela)}"  # noqa: S608
        linhas = self._conexao.execute(sql).fetchall()
        return [
            ColunaSchema(nome=linha[0], tipo=linha[1], aceita_nulo=linha[2] == "YES")
            for linha in linhas
        ]

    def capacidades_suportadas(self) -> Capacidade:
        return Capacidade.CONTAGEM_LINHAS

    def executar_metrica(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        capacidade_necessaria = CAPACIDADE_POR_TIPO_METRICA[especificacao.tipo_metrica]
        if (capacidade_necessaria & self.capacidades_suportadas()) != capacidade_necessaria:
            return ResultadoMetrica(
                dataset=especificacao.dataset,
                tipo_metrica=especificacao.tipo_metrica,
                dimensao=especificacao.dimensao,
                status=StatusResultadoMetrica.NAO_SUPORTADO,
                motivo_nao_suportado=(
                    f"backend '{self.nome_backend}' não suporta {capacidade_necessaria.name} "
                    f"(necessário para {especificacao.tipo_metrica.value})"
                ),
                backend=self.nome_backend,
                linhas_buscadas=0,
                duracao_segundos=0.0,
                coletado_em=datetime.now(),
            )
        if especificacao.tipo_metrica == TipoMetrica.CONTAGEM_LINHAS:
            return self._contagem_linhas(especificacao)
        raise AssertionError(f"tipo de métrica sem implementação: {especificacao.tipo_metrica}")

    def _contagem_linhas(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        sql = f"SELECT COUNT(*) FROM {_identificador_seguro(especificacao.tabela)}"  # noqa: S608
        try:
            linha = instrumentada.execute(sql).fetchone()
        except duckdb.Error as erro:
            return ResultadoMetrica(
                dataset=especificacao.dataset,
                tipo_metrica=especificacao.tipo_metrica,
                dimensao=especificacao.dimensao,
                status=StatusResultadoMetrica.ERRO,
                mensagem_erro=str(erro),
                backend=self.nome_backend,
                linhas_buscadas=instrumentada.linhas_buscadas_total,
                duracao_segundos=time.perf_counter() - inicio,
                coletado_em=datetime.now(),
            )
        if linha is None:
            raise RuntimeError("consulta de contagem de linhas não retornou nenhuma linha")
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            status=StatusResultadoMetrica.OK,
            valor=float(linha[0]),
            tipo_amostragem=TipoAmostragem.FULL_SCAN,
            backend=self.nome_backend,
            linhas_buscadas=instrumentada.linhas_buscadas_total,
            duracao_segundos=time.perf_counter() - inicio,
            coletado_em=datetime.now(),
        )

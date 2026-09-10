"""Adapter de referência: lê datasets DuckDB via SQL empurrado para a própria conexão."""

import time
from collections.abc import Mapping
from datetime import datetime

import duckdb

from obsdados.instrumentacao import ConexaoInstrumentadaDuckDB
from obsdados.nucleo import (
    CAPACIDADE_POR_TIPO_METRICA,
    FRACAO_AMOSTRA_PADRAO,
    GRANULARIDADE_DIA,
    LIMITE_LINHAS_SEM_AMOSTRAGEM,
    PARAMETRO_COLUNAS_SCHEMA,
    PARAMETRO_GRANULARIDADE,
    PARAMETRO_PERMITE_VALOR,
    PARAMETRO_QUANTIL,
    Capacidade,
    ColunaSchema,
    DescricaoDataset,
    EspecificacaoMetrica,
    ResultadoMetrica,
    StatusResultadoMetrica,
    TipoAmostragem,
    TipoMetrica,
)
from obsdados.schema import calcular_hash_schema
from obsdados.sql_util import identificador_seguro as _identificador_seguro

_CAPACIDADES_SUPORTADAS = (
    Capacidade.CONTAGEM_LINHAS
    | Capacidade.FRESCOR
    | Capacidade.SCHEMA_HASH
    | Capacidade.TAXA_NULOS
    | Capacidade.CONTAGEM_DISTINTOS_APROXIMADA
    | Capacidade.MINIMO_MAXIMO
    | Capacidade.QUANTIS
)

_SQL_ESTIMAR_COM_SCHEMA = (
    "SELECT estimated_size FROM duckdb_tables() WHERE schema_name = ? AND table_name = ?"
)
_SQL_ESTIMAR_SEM_SCHEMA = "SELECT estimated_size FROM duckdb_tables() WHERE table_name = ?"


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
        return _CAPACIDADES_SUPORTADAS

    def _estimar_linhas(self, tabela: str) -> int | None:
        schema, _, nome = tabela.rpartition(".")
        if schema:
            linha = self._conexao.execute(_SQL_ESTIMAR_COM_SCHEMA, [schema, nome]).fetchone()
        else:
            linha = self._conexao.execute(_SQL_ESTIMAR_SEM_SCHEMA, [nome]).fetchone()
        return int(linha[0]) if linha and linha[0] is not None else None

    def _decidir_amostragem(self, tabela: str) -> tuple[str, TipoAmostragem]:
        estimado = self._estimar_linhas(tabela)
        if estimado is not None and estimado > LIMITE_LINHAS_SEM_AMOSTRAGEM:
            percentual = round(FRACAO_AMOSTRA_PADRAO * 100)
            return f" USING SAMPLE {percentual} PERCENT (bernoulli)", TipoAmostragem.AMOSTRA
        return "", TipoAmostragem.FULL_SCAN

    def executar_metrica(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        capacidade_necessaria = CAPACIDADE_POR_TIPO_METRICA[especificacao.tipo_metrica]
        if (capacidade_necessaria & self.capacidades_suportadas()) != capacidade_necessaria:
            return self._nao_suportado(especificacao, capacidade_necessaria)

        despachantes = {
            TipoMetrica.CONTAGEM_LINHAS: self._contagem_linhas,
            TipoMetrica.FRESCOR: self._frescor,
            TipoMetrica.SCHEMA_HASH: self._schema_hash,
            TipoMetrica.TAXA_NULOS: self._taxa_nulos,
            TipoMetrica.CARDINALIDADE: self._cardinalidade,
            TipoMetrica.MINIMO: lambda e: self._minimo_maximo(e, "MIN"),
            TipoMetrica.MAXIMO: lambda e: self._minimo_maximo(e, "MAX"),
            TipoMetrica.QUANTIL: self._quantil,
        }
        return despachantes[especificacao.tipo_metrica](especificacao)

    def _nao_suportado(
        self, especificacao: EspecificacaoMetrica, capacidade_necessaria: Capacidade
    ) -> ResultadoMetrica:
        motivo = (
            f"backend '{self.nome_backend}' não suporta {capacidade_necessaria.name} "
            f"(necessário para {especificacao.tipo_metrica.value})"
        )
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            coluna=especificacao.coluna,
            status=StatusResultadoMetrica.NAO_SUPORTADO,
            motivo_nao_suportado=motivo,
            backend=self.nome_backend,
            linhas_buscadas=0,
            duracao_segundos=0.0,
            coletado_em=datetime.now(),
        )

    def _nao_suportado_por_politica(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        motivo = (
            "materialização de valor não autorizada para esta coluna "
            f"(defina parametros.{PARAMETRO_PERMITE_VALOR}=true explicitamente)"
        )
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            coluna=especificacao.coluna,
            status=StatusResultadoMetrica.NAO_SUPORTADO,
            motivo_nao_suportado=motivo,
            backend=self.nome_backend,
            linhas_buscadas=0,
            duracao_segundos=0.0,
            coletado_em=datetime.now(),
        )

    def _erro(
        self, especificacao: EspecificacaoMetrica, mensagem: str, linhas_buscadas: int = 0
    ) -> ResultadoMetrica:
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            coluna=especificacao.coluna,
            status=StatusResultadoMetrica.ERRO,
            mensagem_erro=mensagem,
            backend=self.nome_backend,
            linhas_buscadas=linhas_buscadas,
            duracao_segundos=0.0,
            coletado_em=datetime.now(),
        )

    def _ok(  # noqa: PLR0913
        self,
        especificacao: EspecificacaoMetrica,
        inicio: float,
        linhas_buscadas: int,
        *,
        valor: float | None = None,
        valor_texto: str | None = None,
        tipo_amostragem: TipoAmostragem = TipoAmostragem.FULL_SCAN,
        parametros: Mapping[str, object] | None = None,
    ) -> ResultadoMetrica:
        return ResultadoMetrica(
            dataset=especificacao.dataset,
            tipo_metrica=especificacao.tipo_metrica,
            dimensao=especificacao.dimensao,
            coluna=especificacao.coluna,
            status=StatusResultadoMetrica.OK,
            valor=valor,
            valor_texto=valor_texto,
            tipo_amostragem=tipo_amostragem,
            backend=self.nome_backend,
            linhas_buscadas=linhas_buscadas,
            duracao_segundos=time.perf_counter() - inicio,
            coletado_em=datetime.now(),
            parametros=especificacao.parametros if parametros is None else parametros,
        )

    def _contagem_linhas(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        tabela_segura = _identificador_seguro(especificacao.tabela)
        where = ""
        valores: list[object] = []
        if especificacao.dimensao is not None:
            if not especificacao.coluna:
                return self._erro(especificacao, "contagem por dimensão exige coluna")
            coluna_segura = _identificador_seguro(especificacao.coluna)
            por_dia = especificacao.parametros.get(PARAMETRO_GRANULARIDADE) == GRANULARIDADE_DIA
            if por_dia:
                esquerda = f"date_trunc('day', {coluna_segura})"
                direita = "date_trunc('day', CAST(? AS TIMESTAMP))"
                where = f" WHERE {esquerda} = {direita}"
            else:
                where = f" WHERE {coluna_segura} = ?"
            valores = [especificacao.dimensao]
        sql = f"SELECT COUNT(*) FROM {tabela_segura}{where}"  # noqa: S608
        try:
            linha = instrumentada.execute(sql, valores).fetchone()
        except duckdb.Error as erro:
            return self._erro(especificacao, str(erro), instrumentada.linhas_buscadas_total)
        if linha is None:
            raise RuntimeError("consulta de contagem de linhas não retornou nenhuma linha")
        buscadas = instrumentada.linhas_buscadas_total
        return self._ok(especificacao, inicio, buscadas, valor=float(linha[0]))

    def _frescor(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        if not especificacao.coluna:
            return self._erro(especificacao, "frescor exige coluna com o timestamp de referência")
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        coluna_segura = _identificador_seguro(especificacao.coluna)
        tabela_segura = _identificador_seguro(especificacao.tabela)
        sql = f"SELECT epoch(now() - MAX({coluna_segura})) FROM {tabela_segura}"  # noqa: S608
        try:
            linha = instrumentada.execute(sql).fetchone()
        except duckdb.Error as erro:
            return self._erro(especificacao, str(erro), instrumentada.linhas_buscadas_total)
        buscadas = instrumentada.linhas_buscadas_total
        if linha is None or linha[0] is None:
            return self._erro(especificacao, "tabela vazia, frescor indefinido", buscadas)
        return self._ok(especificacao, inicio, buscadas, valor=float(linha[0]))

    def _schema_hash(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        inicio = time.perf_counter()
        colunas = self.descrever_schema(especificacao.tabela)
        hash_atual = calcular_hash_schema(colunas)
        return self._ok(
            especificacao,
            inicio,
            linhas_buscadas=len(colunas),
            valor_texto=hash_atual,
            parametros={PARAMETRO_COLUNAS_SCHEMA: [c.model_dump() for c in colunas]},
        )

    def _taxa_nulos(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        if not especificacao.coluna:
            return self._erro(especificacao, "taxa_nulos exige coluna")
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        coluna_segura = _identificador_seguro(especificacao.coluna)
        sufixo_amostra, tipo_amostragem = self._decidir_amostragem(especificacao.tabela)
        tabela_segura = _identificador_seguro(especificacao.tabela)
        sql = (
            f"SELECT 1.0 - COUNT({coluna_segura})::DOUBLE / NULLIF(COUNT(*), 0) "  # noqa: S608
            f"FROM {tabela_segura}{sufixo_amostra}"
        )
        try:
            linha = instrumentada.execute(sql).fetchone()
        except duckdb.Error as erro:
            return self._erro(especificacao, str(erro), instrumentada.linhas_buscadas_total)
        buscadas = instrumentada.linhas_buscadas_total
        if linha is None or linha[0] is None:
            return self._erro(especificacao, "tabela vazia, taxa de nulos indefinida", buscadas)
        return self._ok(
            especificacao, inicio, buscadas, valor=float(linha[0]), tipo_amostragem=tipo_amostragem
        )

    def _cardinalidade(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        if not especificacao.coluna:
            return self._erro(especificacao, "cardinalidade exige coluna")
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        coluna_segura = _identificador_seguro(especificacao.coluna)
        sufixo_amostra, tipo_amostragem = self._decidir_amostragem(especificacao.tabela)
        tabela_segura = _identificador_seguro(especificacao.tabela)
        sql = (
            f"SELECT approx_count_distinct({coluna_segura}) "  # noqa: S608
            f"FROM {tabela_segura}{sufixo_amostra}"
        )
        try:
            linha = instrumentada.execute(sql).fetchone()
        except duckdb.Error as erro:
            return self._erro(especificacao, str(erro), instrumentada.linhas_buscadas_total)
        if linha is None:
            raise RuntimeError("consulta de cardinalidade não retornou nenhuma linha")
        buscadas = instrumentada.linhas_buscadas_total
        return self._ok(
            especificacao, inicio, buscadas, valor=float(linha[0]), tipo_amostragem=tipo_amostragem
        )

    def _minimo_maximo(
        self, especificacao: EspecificacaoMetrica, funcao_sql: str
    ) -> ResultadoMetrica:
        if not especificacao.coluna:
            return self._erro(especificacao, f"{especificacao.tipo_metrica.value} exige coluna")
        if especificacao.parametros.get(PARAMETRO_PERMITE_VALOR) is not True:
            return self._nao_suportado_por_politica(especificacao)
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        coluna_segura = _identificador_seguro(especificacao.coluna)
        sufixo_amostra, tipo_amostragem = self._decidir_amostragem(especificacao.tabela)
        tabela_segura = _identificador_seguro(especificacao.tabela)
        sql = f"SELECT {funcao_sql}({coluna_segura}) FROM {tabela_segura}{sufixo_amostra}"  # noqa: S608
        try:
            linha = instrumentada.execute(sql).fetchone()
        except duckdb.Error as erro:
            return self._erro(especificacao, str(erro), instrumentada.linhas_buscadas_total)
        buscadas = instrumentada.linhas_buscadas_total
        if linha is None or linha[0] is None:
            return self._erro(especificacao, "tabela vazia, sem valor", buscadas)
        return self._ok(
            especificacao, inicio, buscadas,
            valor_texto=str(linha[0]), tipo_amostragem=tipo_amostragem,
        )

    def _quantil(self, especificacao: EspecificacaoMetrica) -> ResultadoMetrica:
        if not especificacao.coluna:
            return self._erro(especificacao, "quantil exige coluna")
        quantil = especificacao.parametros.get(PARAMETRO_QUANTIL)
        if not isinstance(quantil, int | float) or not 0 < quantil < 1:
            return self._erro(especificacao, "quantil exige parametros.quantil entre 0 e 1")
        if especificacao.parametros.get(PARAMETRO_PERMITE_VALOR) is not True:
            return self._nao_suportado_por_politica(especificacao)
        inicio = time.perf_counter()
        instrumentada = ConexaoInstrumentadaDuckDB(self._conexao)
        coluna_segura = _identificador_seguro(especificacao.coluna)
        sufixo_amostra, tipo_amostragem = self._decidir_amostragem(especificacao.tabela)
        tabela_segura = _identificador_seguro(especificacao.tabela)
        sql = (
            f"SELECT quantile_cont({coluna_segura}, ?) "  # noqa: S608
            f"FROM {tabela_segura}{sufixo_amostra}"
        )
        try:
            linha = instrumentada.execute(sql, [quantil]).fetchone()
        except duckdb.Error as erro:
            return self._erro(especificacao, str(erro), instrumentada.linhas_buscadas_total)
        buscadas = instrumentada.linhas_buscadas_total
        if linha is None or linha[0] is None:
            return self._erro(especificacao, "tabela vazia, sem quantil", buscadas)
        return self._ok(
            especificacao, inicio, buscadas, valor=float(linha[0]), tipo_amostragem=tipo_amostragem
        )

"""Catálogo técnico e mapeamento semântico de colunas."""

from __future__ import annotations

import logging
import re
import unicodedata

import pandas as pd

from app.servicos.azure_sql_service import AzureSqlService
from app.servicos.base_service import BaseService
from app.servicos.config import Config
from app.servicos.data_service import DataService


class MetadataService(BaseService):
    """Gerencia dicionário de dados e sinônimos de negócio."""

    NOME_DICIONARIO = "dicionario_dados"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        data_service: DataService,
        azure_sql_service: AzureSqlService | None = None,
    ) -> None:
        super().__init__(config, logger)
        self._data_service = data_service
        self._azure_sql_service = azure_sql_service
        self._mapeamento: dict[str, str] = {}
        self._descricoes: dict[str, str] = {}
        self._carregar_dicionario()

    def _carregar_dicionario(self) -> None:
        try:
            df = self._data_service.obter(self.NOME_DICIONARIO)
        except KeyError:
            self.logger.warning(
                "Arquivo %s.xlsx não encontrado — metadados indisponíveis.",
                self.NOME_DICIONARIO,
            )
            return

        colunas = {self._normalizar(c): c for c in df.columns}
        col_tecnica = self._resolver_coluna(colunas, ["coluna_tecnica", "coluna", "campo", "field"])
        col_sinonimo = self._resolver_coluna(colunas, ["sinonimo", "sinonimos", "termo", "alias"])
        col_descricao = self._resolver_coluna(colunas, ["descricao", "description", "definicao"])

        if not col_tecnica or not col_sinonimo:
            self.logger.error("Dicionário de dados sem colunas técnicas/sinônimos reconhecidas.")
            return

        for _, linha in df.iterrows():
            tecnica = str(linha[col_tecnica]).strip()
            sinonimo_bruto = str(linha[col_sinonimo]).strip()
            if not tecnica or tecnica.lower() == "nan":
                continue

            for termo in re.split(r"[;,|/]", sinonimo_bruto):
                termo_limpo = termo.strip()
                if termo_limpo:
                    self._mapeamento[self._normalizar(termo_limpo)] = tecnica

            self._mapeamento[self._normalizar(tecnica)] = tecnica

            if col_descricao and pd.notna(linha[col_descricao]):
                self._descricoes[tecnica] = str(linha[col_descricao]).strip()

        self.logger.info("Metadados carregados: %d sinônimos mapeados.", len(self._mapeamento))

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", texto.lower().strip())

    @staticmethod
    def _resolver_coluna(colunas: dict[str, str], candidatos: list[str]) -> str | None:
        for candidato in candidatos:
            if candidato in colunas:
                return colunas[candidato]
        return None

    def localizar_coluna(self, pergunta: str) -> list[str]:
        """Identifica colunas técnicas mencionadas ou inferidas na pergunta."""
        pergunta_norm = self._normalizar(pergunta)
        encontradas: list[str] = []

        for sinonimo, coluna in sorted(self._mapeamento.items(), key=lambda x: len(x[0]), reverse=True):
            if sinonimo in pergunta_norm and coluna not in encontradas:
                encontradas.append(coluna)

        return encontradas

    def obter_catalogo_texto(self) -> str:
        """Retorna catálogo legível para enriquecimento de prompts."""
        if not self._mapeamento:
            return "Catálogo de metadados indisponível."

        linhas = ["Coluna técnica | Sinônimos | Descrição"]
        agrupado: dict[str, list[str]] = {}
        for sinonimo, coluna in self._mapeamento.items():
            agrupado.setdefault(coluna, [])
            if sinonimo != self._normalizar(coluna):
                agrupado[coluna].append(sinonimo)

        for coluna in sorted(agrupado):
            sinonimos = ", ".join(sorted(set(agrupado[coluna])))
            descricao = self._descricoes.get(coluna, "")
            linhas.append(f"{coluna} | {sinonimos} | {descricao}")

        return "\n".join(linhas)

    def obter_tabelas_disponiveis(self, nomes: list[str]) -> str:
        """Resume estrutura das tabelas disponíveis para geração de SQL."""
        if self.config.fonte_dados == "azure" and self._azure_sql_service:
            return self._azure_sql_service.descrever_tabelas()

        blocos: list[str] = []
        for nome in nomes:
            try:
                df = self._data_service.obter(nome)
                colunas = ", ".join(df.columns.astype(str).tolist())
                blocos.append(f"Tabela `{nome}`: colunas [{colunas}]")
            except KeyError:
                continue
        return "\n".join(blocos) if blocos else "Nenhuma tabela disponível."

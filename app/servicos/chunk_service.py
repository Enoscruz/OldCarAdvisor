"""Chunking de documentos com LangChain Text Splitters."""

from __future__ import annotations

import logging

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.servicos.base_service import BaseService
from app.servicos.config import Config
from app.servicos.data_service import DataService


class ChunkService(BaseService):
    """Carrega fontes de conhecimento e divide em chunks."""

    NOME_DICIONARIO = "dicionario_dados"
    EXTENSOES = (".txt", ".md")

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        data_service: DataService,
    ) -> None:
        super().__init__(config, logger)
        self._data_service = data_service
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_tamanho,
            chunk_overlap=self.config.chunk_sobreposicao,
            separators=["\n\n", "\n", ". ", "; ", " ", ""],
        )

    def montar_documentos(self) -> list[Document]:
        """Reúne documentos brutos (dicionário + arquivos de conhecimento)."""
        documentos: list[Document] = []
        documentos.extend(self._documentos_dicionario())
        documentos.extend(self._documentos_arquivos())
        self.logger.info("Documentos brutos carregados: %d", len(documentos))
        return documentos

    def dividir(self, documentos: list[Document] | None = None) -> list[Document]:
        """Aplica chunking e devolve trechos prontos para embedding."""
        origem = documentos if documentos is not None else self.montar_documentos()
        if not origem:
            return []
        chunks = self._splitter.split_documents(origem)
        self.logger.info("Chunks gerados: %d (tamanho=%d, overlap=%d)", len(chunks), self.config.chunk_tamanho, self.config.chunk_sobreposicao)
        return chunks

    def _documentos_dicionario(self) -> list[Document]:
        try:
            df = self._data_service.obter(self.NOME_DICIONARIO)
        except KeyError:
            self.logger.warning("dicionario_dados.xlsx não encontrado para indexação RAG.")
            return []

        colunas = {str(c).strip().lower(): c for c in df.columns}
        col_tecnica = self._resolver(colunas, ["coluna_tecnica", "coluna", "campo"])
        col_sinonimo = self._resolver(colunas, ["sinonimo", "sinonimos", "termo"])
        col_descricao = self._resolver(colunas, ["descricao", "description", "definicao"])

        documentos: list[Document] = []
        for indice, linha in df.iterrows():
            tecnica = self._texto(linha, col_tecnica)
            if not tecnica:
                continue
            sinonimos = self._texto(linha, col_sinonimo)
            descricao = self._texto(linha, col_descricao)
            conteudo = (
                f"Coluna técnica: {tecnica}\n"
                f"Sinônimos: {sinonimos or 'não informado'}\n"
                f"Descrição: {descricao or 'não informado'}"
            )
            documentos.append(
                Document(
                    page_content=conteudo,
                    metadata={
                        "fonte": "dicionario_dados",
                        "coluna": tecnica,
                        "linha": int(indice) if str(indice).isdigit() else indice,
                    },
                )
            )
        return documentos

    def _documentos_arquivos(self) -> list[Document]:
        pasta = self.config.pasta_conhecimento
        if not pasta.exists():
            return []

        documentos: list[Document] = []
        for arquivo in pasta.rglob("*"):
            if arquivo.suffix.lower() not in self.EXTENSOES:
                continue
            try:
                texto = arquivo.read_text(encoding="utf-8")
            except Exception as exc:
                self.logger.error("Falha ao ler %s: %s", arquivo, exc)
                continue
            if not texto.strip():
                continue
            documentos.append(
                Document(
                    page_content=texto,
                    metadata={"fonte": str(arquivo.relative_to(self.config.raiz_projeto)), "arquivo": arquivo.name},
                )
            )
        return documentos

    @staticmethod
    def _resolver(colunas: dict[str, str], candidatos: list[str]) -> str | None:
        for candidato in candidatos:
            if candidato in colunas:
                return colunas[candidato]
        return None

    @staticmethod
    def _texto(linha: pd.Series, coluna: str | None) -> str:
        if not coluna or coluna not in linha.index:
            return ""
        valor = linha[coluna]
        if pd.isna(valor):
            return ""
        texto = str(valor).strip()
        return "" if texto.lower() == "nan" else texto

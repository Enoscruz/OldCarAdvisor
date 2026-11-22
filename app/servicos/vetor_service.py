"""Banco de dados vetorial (Chroma) via LangChain.

Indexa o conhecimento da consultoria (fichas técnicas dos clássicos e os
arquivos de apoio sobre estilos, crônicos, mercado e peças) e executa a busca
por similaridade usada pelo RAG. O índice é persistido em disco e só é
reconstruído quando a assinatura dos documentos muda — assim a plataforma não
paga o custo de reindexar a cada inicialização.
"""

from __future__ import annotations

import logging
import shutil
from hashlib import sha256

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.servicos.base_service import BaseService
from app.servicos.conhecimento_service import ConhecimentoService
from app.servicos.config import Config
from app.servicos.embedding_service import EmbeddingService


class VetorService(BaseService):
    """Indexa os documentos do domínio e executa busca por similaridade."""

    COLECAO = "classicos_rag"
    ARQUIVO_ASSINATURA = "assinatura.txt"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        embedding_service: EmbeddingService,
        conhecimento_service: ConhecimentoService,
    ) -> None:
        super().__init__(config, logger)
        self._embedding_service = embedding_service
        self._conhecimento_service = conhecimento_service
        self._store: Chroma | None = None
        self.garantir_indice()

    def embeddings(self) -> Embeddings:
        return self._embedding_service.obter()

    def garantir_indice(self, forcar: bool = False) -> None:
        """Cria ou reutiliza o índice, reindexando só se a base mudou."""
        pasta = self.config.pasta_vetores
        pasta.mkdir(parents=True, exist_ok=True)

        documentos = self._conhecimento_service.preparar_documentos()
        assinatura = self._assinatura(documentos)

        if forcar:
            shutil.rmtree(pasta, ignore_errors=True)
            pasta.mkdir(parents=True, exist_ok=True)
            self._store = None

        store = self._abrir_store()
        desatualizado = self._contar(store) == 0 or self._ler_assinatura() != assinatura
        if desatualizado:
            self._indexar(documentos)
            self._gravar_assinatura(assinatura)
            store = self._abrir_store()

        self.logger.info(
            "Índice vetorial pronto: %d vetor(es) de %d documento(s) em %s",
            self._contar(store),
            len(documentos),
            pasta,
        )

    def indexar(self) -> int:
        """Reindexa à força a partir do conhecimento corrente."""
        documentos = self._conhecimento_service.preparar_documentos()
        quantidade = self._indexar(documentos)
        self._gravar_assinatura(self._assinatura(documentos))
        return quantidade

    def buscar(
        self,
        consulta: str,
        k: int | None = None,
        filtro: dict | None = None,
    ) -> list[Document]:
        """Recupera os k trechos mais similares à consulta."""
        if not consulta.strip():
            return []
        limite = k or self.config.rag_k
        store = self._abrir_store()
        if self._contar(store) == 0:
            return []
        documentos = store.similarity_search(consulta, k=limite, filter=filtro)
        self.logger.info("Busca vetorial retornou %d trecho(s).", len(documentos))
        return documentos

    # ------------------------------------------------------------------
    def _indexar(self, documentos: list[Document]) -> int:
        if not documentos:
            self.logger.warning("Nenhum documento para indexar.")
            return 0

        # IDs determinísticos tornam a indexação reprodutível e evitam duplicatas.
        ids = [self._id_documento(documento) for documento in documentos]
        try:
            self._abrir_store().delete_collection()
        except Exception:
            pass
        self._store = None
        store = self._abrir_store()
        store.add_documents(documents=documentos, ids=ids)
        self.logger.info("Indexados %d documento(s) no Chroma.", len(documentos))
        return len(documentos)

    def _abrir_store(self) -> Chroma:
        if self._store is None:
            self._store = Chroma(
                collection_name=self.COLECAO,
                embedding_function=self.embeddings(),
                persist_directory=str(self.config.pasta_vetores),
            )
        return self._store

    def _ler_assinatura(self) -> str:
        caminho = self.config.pasta_vetores / self.ARQUIVO_ASSINATURA
        if not caminho.exists():
            return ""
        try:
            return caminho.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _gravar_assinatura(self, assinatura: str) -> None:
        caminho = self.config.pasta_vetores / self.ARQUIVO_ASSINATURA
        try:
            caminho.write_text(assinatura, encoding="utf-8")
        except Exception as exc:
            self.logger.warning("Falha ao gravar assinatura do índice: %s", exc)

    @staticmethod
    def _contar(store: Chroma) -> int:
        try:
            return int(store._collection.count())  # noqa: SLF001
        except Exception:
            return 0

    @classmethod
    def _assinatura(cls, documentos: list[Document]) -> str:
        base = "\n".join(cls._id_documento(documento) for documento in documentos)
        return sha256(base.encode("utf-8")).hexdigest()

    @staticmethod
    def _id_documento(documento: Document) -> str:
        origem = str(documento.metadata.get("fonte", ""))
        conteudo = f"{origem}\n{documento.page_content}".encode("utf-8")
        return f"doc-{sha256(conteudo).hexdigest()}"

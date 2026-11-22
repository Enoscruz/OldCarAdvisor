"""Geração de embeddings via LangChain (local ONNX, Vertex ou fake)."""

from __future__ import annotations

import logging
import hashlib
import re
import unicodedata

from langchain_core.embeddings import Embeddings, FakeEmbeddings

from app.servicos.base_service import BaseService
from app.servicos.config import Config


class EmbeddingChromaOnnx(Embeddings):
    """Embeddings locais do Chroma (all-MiniLM via ONNX), sem PyTorch."""

    def __init__(self) -> None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._funcao = DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return list(self._funcao(texts))

    def embed_query(self, text: str) -> list[float]:
        return list(self._funcao([text])[0])


class EmbeddingHashLocal(Embeddings):
    """Embedding local determinístico, sem download de modelo externo.

    É adequado ao modo offline e mantém o mesmo vetor para um texto entre
    reinicializações, o que é essencial para um índice Chroma persistido.
    """

    def __init__(self, tamanho: int = 384) -> None:
        self._tamanho = tamanho

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vetor(texto) for texto in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vetor(text)

    def _vetor(self, texto: str) -> list[float]:
        normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
        tokens = re.findall(r"[a-z0-9_]+", normalizado.lower())
        vetor = [0.0] * self._tamanho
        for token in tokens:
            indice = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:4], "big") % self._tamanho
            vetor[indice] += 1.0
        norma = sum(valor * valor for valor in vetor) ** 0.5
        return [valor / norma for valor in vetor] if norma else vetor


class EmbeddingService(BaseService):
    """Fornece a implementação de embeddings conforme EMBEDDING_MODO."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self._embeddings: Embeddings | None = None

    def obter(self) -> Embeddings:
        if self._embeddings is None:
            self._embeddings = self._criar()
        return self._embeddings

    def _criar(self) -> Embeddings:
        modo = self.config.embedding_modo
        if modo == "fake":
            self.logger.info("Embeddings em modo FAKE (vetores sintéticos).")
            return FakeEmbeddings(size=384)

        if modo == "vertex":
            try:
                from langchain_google_vertexai import VertexAIEmbeddings

                self.logger.info("Embeddings Vertex AI: text-embedding-004")
                return VertexAIEmbeddings(
                    model_name="text-embedding-004",
                    project=self.config.google_cloud_project or None,
                    location=self.config.google_cloud_location,
                )
            except Exception as exc:
                self.logger.warning("Falha ao iniciar Vertex embeddings (%s). Usando local.", exc)

        self.logger.info("Embeddings locais determinísticos (hashing, sem download de modelo).")
        return EmbeddingHashLocal()

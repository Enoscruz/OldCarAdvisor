"""Base de conhecimento que alimenta o RAG da consultoria.

Reúne duas fontes em `Document`s do LangChain:

- o catálogo local de clássicos — uma ficha técnica por veículo, mantida
  inteira (sem divisão) para que os dados de um carro nunca fiquem espalhados
  entre chunks diferentes;
- os arquivos de texto/markdown de `PASTA_CONHECIMENTO` (engenharia, crônicos,
  mercado e peças), que são divididos em chunks por serem textos corridos.
"""

from __future__ import annotations

import logging

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.servicos.base_service import BaseService
from app.servicos.catalogo_service import CatalogoService
from app.servicos.config import Config

# Campos do catálogo que viram texto indexável na ficha técnica.
CAMPOS_FICHA: tuple[tuple[str, str], ...] = (
    ("montadora", "Montadora"),
    ("anos", "Anos"),
    ("origem", "Origem"),
    ("tracao", "Tração"),
    ("peso_kg", "Peso (kg)"),
    ("susp_dianteira", "Suspensão dianteira"),
    ("susp_traseira", "Suspensão traseira"),
    ("motor_factory", "Motor de fábrica"),
    ("potencia_cv", "Potência (cv)"),
    ("cofre_motor", "Cofre do motor"),
    ("potencial_swap", "Potencial de swap"),
    ("estilos_ideais", "Estilos ideais"),
    ("preco_entrada_medio", "Preço de entrada médio (R$)"),
    ("valor_fipe_ref", "Referência FIPE (R$)"),
    ("custo_build_estimado", "Custo de build estimado (R$)"),
    ("pecas_lataria", "Peças de lataria"),
    ("pecas_mecanica", "Peças de mecânica"),
    ("aftermarket_importado", "Aftermarket importado"),
    ("risco_ferrugem", "Risco de ferrugem"),
    ("eletrica", "Elétrica"),
    ("cronicos_conhecidos", "Crônicos conhecidos"),
)

FONTE_CATALOGO = "catalogo_carros"


class ConhecimentoService(BaseService):
    """Monta os documentos indexados na base vetorial."""

    EXTENSOES = (".txt", ".md")

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        catalogo_service: CatalogoService,
    ) -> None:
        super().__init__(config, logger)
        self._catalogo = catalogo_service
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_tamanho,
            chunk_overlap=self.config.chunk_sobreposicao,
            separators=["\n## ", "\n\n", "\n", ". ", " ", ""],
        )

    def preparar_documentos(self) -> list[Document]:
        """Devolve as fichas do catálogo e os chunks dos arquivos de apoio."""
        fichas = self._documentos_catalogo()
        chunks = self._splitter.split_documents(self._documentos_arquivos())
        self.logger.info(
            "Base de conhecimento: %d ficha(s) do catálogo + %d chunk(s) de arquivos.",
            len(fichas),
            len(chunks),
        )
        return fichas + chunks

    def _documentos_catalogo(self) -> list[Document]:
        try:
            df = self._catalogo.listar()
        except Exception as exc:
            self.logger.error("Falha ao ler o catálogo para o RAG: %s", exc)
            return []
        if df.empty:
            return []

        documentos: list[Document] = []
        for _, linha in df.iterrows():
            modelo = self._texto(linha, "modelo")
            if not modelo:
                continue
            partes = [f"Ficha técnica do {modelo}."]
            for campo, rotulo in CAMPOS_FICHA:
                valor = self._texto(linha, campo)
                if valor:
                    partes.append(f"{rotulo}: {valor}.")
            documentos.append(
                Document(
                    page_content=" ".join(partes),
                    metadata={
                        "fonte": FONTE_CATALOGO,
                        "tipo": "ficha_tecnica",
                        "modelo": modelo,
                        "montadora": self._texto(linha, "montadora"),
                    },
                )
            )
        return documentos

    def _documentos_arquivos(self) -> list[Document]:
        pasta = self.config.pasta_conhecimento
        if not pasta.exists():
            return []

        documentos: list[Document] = []
        for arquivo in sorted(pasta.rglob("*")):
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
                    metadata={
                        "fonte": str(arquivo.relative_to(self.config.raiz_projeto)).replace("\\", "/"),
                        "tipo": "conhecimento",
                        "modelo": "",
                    },
                )
            )
        return documentos

    @staticmethod
    def _texto(linha: pd.Series, coluna: str) -> str:
        if coluna not in linha.index:
            return ""
        valor = linha[coluna]
        if valor is None or pd.isna(valor):
            return ""
        texto = str(valor).strip()
        return "" if texto.lower() == "nan" else texto

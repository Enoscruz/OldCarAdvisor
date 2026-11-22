"""Catálogo local de clássicos e seleção de candidatos.

O catálogo (dados/catalogo_carros.csv) funciona como base offline: garante que
a plataforma produza uma consultoria mesmo sem internet ou sem o retorno das
APIs externas. É também a fonte do shortlist inicial, filtrado por orçamento
de entrada e estilo de customização desejado.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from app.servicos.base_service import BaseService
from app.servicos.config import Config

COLUNAS_NUMERICAS = (
    "peso_kg", "potencia_cv", "preco_entrada_medio", "faixa_preco_min",
    "faixa_preco_max", "valor_fipe_ref", "custo_build_estimado",
)


class CatalogoService(BaseService):
    """Carrega o catálogo de veículos e monta o shortlist de candidatos."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self._df = self._carregar()

    # ------------------------------------------------------------------
    # Carregamento
    # ------------------------------------------------------------------
    def _carregar(self) -> pd.DataFrame:
        base = self.config.pasta_dados / self.config.catalogo_veiculos
        for caminho, separador in ((base.with_suffix(".csv"), ";"), (base.with_suffix(".xlsx"), None)):
            if not caminho.exists():
                continue
            try:
                df = pd.read_csv(caminho, sep=separador) if separador else pd.read_excel(caminho)
            except Exception as exc:
                self.logger.error("Falha ao ler catálogo %s: %s", caminho.name, exc)
                continue
            df.columns = [str(c).strip().lower() for c in df.columns]
            for coluna in COLUNAS_NUMERICAS:
                if coluna in df.columns:
                    df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
            if "estilos_ideais" in df.columns:
                df["estilos_ideais"] = df["estilos_ideais"].fillna("").astype(str)
            self.logger.info("Catálogo carregado: %d veículo(s) de %s.", len(df), caminho.name)
            return df

        self.logger.warning("Catálogo de veículos não encontrado em %s.", base)
        return pd.DataFrame()

    @property
    def vazio(self) -> bool:
        return self._df.empty

    def listar(self) -> pd.DataFrame:
        """Cópia do catálogo completo."""
        return self._df.copy()

    def modelos(self) -> list[str]:
        if "modelo" not in self._df.columns:
            return []
        return self._df["modelo"].astype(str).tolist()

    # ------------------------------------------------------------------
    # Seleção de candidatos
    # ------------------------------------------------------------------
    def selecionar_candidatos(
        self,
        orcamento: float | None,
        estilo: str,
        termo_livre: str = "",
        limite: int | None = None,
    ) -> list[dict]:
        """Monta o shortlist de carros compatíveis com orçamento e estilo.

        Se o usuário citou um modelo específico que existe no catálogo, ele é
        priorizado. Caso contrário, filtra por orçamento de entrada e ranqueia
        pela aderência ao estilo desejado.
        """
        if self.vazio:
            return []

        limite = limite or self.config.max_candidatos
        estilo = (estilo or "GERAL").upper()
        entrada_max = orcamento * self.config.fracao_entrada_orcamento if orcamento else None

        candidatos = [self._para_dict(linha) for _, linha in self._df.iterrows()]

        citado = self._localizar_por_termo(termo_livre, candidatos)
        if citado:
            for candidato in candidatos:
                candidato["prioridade_usuario"] = candidato["modelo"] == citado["modelo"]
            candidatos.sort(key=lambda c: (not c["prioridade_usuario"], c["preco_entrada_medio"]))
            return candidatos[: max(limite, 1)]

        for candidato in candidatos:
            candidato["aderencia_estilo"] = self._aderencia(estilo, candidato["estilos_ideais"])
            candidato["entrada_dentro_orcamento"] = (
                entrada_max is None or candidato["preco_entrada_medio"] <= entrada_max
            )

        dentro = [c for c in candidatos if c["entrada_dentro_orcamento"]]
        if not dentro:
            # Nada cabe no orçamento: devolve os mais baratos e sinaliza o problema.
            candidatos.sort(key=lambda c: c["preco_entrada_medio"])
            for candidato in candidatos[:limite]:
                candidato["entrada_dentro_orcamento"] = False
            return candidatos[:limite]

        dentro.sort(
            key=lambda c: (-c["aderencia_estilo"], c["preco_entrada_medio"]),
        )
        return dentro[:limite]

    def _localizar_por_termo(self, termo: str, candidatos: list[dict]) -> dict | None:
        if not termo:
            return None
        termo_norm = self._normalizar(termo)
        for candidato in candidatos:
            if self._normalizar(candidato["modelo"]) in termo_norm:
                return candidato
        return None

    def _para_dict(self, linha: pd.Series) -> dict:
        estilos = [
            e.strip().upper()
            for e in str(linha.get("estilos_ideais", "")).split("|")
            if e.strip()
        ]
        dados = {str(k): (None if pd.isna(v) else v) for k, v in linha.items()}
        dados["estilos_ideais"] = estilos
        return dados

    @staticmethod
    def _aderencia(estilo: str, estilos_ideais: list[str]) -> int:
        if not estilos_ideais:
            return 0
        if estilo in estilos_ideais:
            return 2
        if "GERAL" in estilos_ideais:
            return 1
        return 0

    @staticmethod
    def _normalizar(texto: str) -> str:
        import unicodedata

        texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
        return texto.lower().strip()

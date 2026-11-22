"""Extração do briefing do usuário a partir de texto livre.

Transforma pedidos como "tenho R$ 90 mil para um Opala hot rod no Paraná" em
campos estruturados (orçamento, estilo, região) que alimentam os agentes.
A extração é determinística (regex + palavras-chave): não depende de LLM e
funciona offline.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from app.servicos.base_service import BaseService
from app.servicos.config import Config

# Palavras-chave -> estilo de customização (ordem importa: a primeira achada vence).
PALAVRAS_ESTILO: tuple[tuple[str, str], ...] = (
    ("restomod", "RESTOMOD"),
    ("resto mod", "RESTOMOD"),
    ("hot rod", "HOT_ROD"),
    ("hotrod", "HOT_ROD"),
    ("stance", "STANCE"),
    ("rebaixado", "STANCE"),
    ("baixinho", "STANCE"),
    ("euro", "EURO"),
    ("europeu", "EURO"),
    ("turbo", "TURBO"),
    ("turbinado", "TURBO"),
    ("drift", "DRIFT"),
    ("off road", "OFF_ROAD"),
    ("offroad", "OFF_ROAD"),
    ("4x4", "OFF_ROAD"),
    ("levantado", "OFF_ROAD"),
    ("trilha", "OFF_ROAD"),
)

PALAVRAS_REGIAO = ("sul", "sudeste", "nordeste", "norte", "centro-oeste", "centro oeste")


class BriefingService(BaseService):
    """Interpreta o pedido do usuário e devolve o briefing estruturado."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)

    def extrair(self, pergunta: str) -> dict:
        """Retorna {'orcamento', 'estilo', 'regiao', 'restricoes'}."""
        texto = pergunta or ""
        briefing = {
            "orcamento": self._extrair_orcamento(texto),
            "estilo": self._extrair_estilo(texto),
            "regiao": self._extrair_regiao(texto),
            "restricoes": "",
        }
        self.logger.info(
            "Briefing extraído: orçamento=%s, estilo=%s, região=%s",
            briefing["orcamento"], briefing["estilo"], briefing["regiao"] or "não informada",
        )
        return briefing

    @staticmethod
    def _extrair_orcamento(texto: str) -> float | None:
        normalizado = texto.lower().replace("\u00a0", " ")
        # "R$ 80.000", "r$80000", "R$ 80.000,00" — remove separador de milhar.
        com_moeda = re.sub(r"(?<=\d)\.(?=\d{3})", "", normalizado)

        # "R$ 90 mil", "90k", "120 mil" — sufixo multiplicador tem prioridade,
        # senão "R$ 90 mil" seria lido como R$ 90.
        match = re.search(r"(?:r\$\s*)?([\d]+)\s*(mil|k)\b", com_moeda)
        if match:
            return float(match.group(1)) * 1000

        match = re.search(r"r\$\s*([\d]+)", com_moeda)
        if match:
            return float(match.group(1))

        for match in re.finditer(r"([\d]{4,})", com_moeda.replace(".", "")):
            valor = float(match.group(1))
            if 1900 <= valor <= 2035:  # evita confundir ano-modelo com orçamento
                continue
            return valor
        return None

    @staticmethod
    def _extrair_estilo(texto: str) -> str:
        normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()
        for palavra, estilo in PALAVRAS_ESTILO:
            if palavra in normalizado:
                return estilo
        return "GERAL"

    @staticmethod
    def _extrair_regiao(texto: str) -> str:
        normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()
        for regiao in PALAVRAS_REGIAO:
            if regiao in normalizado:
                return regiao
        return ""

"""Busca na internet para os agentes de Aftermarket e de Crônicos.

Usa o DuckDuckGo (pacote `ddgs`, sem necessidade de chave de API) para
levantar disponibilidade de peças e relatos de fóruns. Se o pacote não
estiver instalado, a busca estiver desabilitada ou a rede falhar, devolve
uma lista vazia — os agentes então seguem apenas com o catálogo local.
"""

from __future__ import annotations

import logging

from app.servicos.base_service import BaseService
from app.servicos.config import Config


class BuscaWebService(BaseService):
    """Executa buscas textuais na web e devolve resultados normalizados."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self._motor = self._criar_motor()

    def pesquisar(self, consulta: str, max_resultados: int | None = None) -> list[dict]:
        """Retorna [{'titulo', 'url', 'resumo'}] ou [] quando indisponível."""
        if not self.config.integracoes_online or self._motor is None or not consulta.strip():
            return []
        limite = max_resultados or self.config.busca_web_max
        try:
            resultados = self._motor.text(consulta, max_results=limite)
        except Exception as exc:
            self.logger.warning("Busca web falhou (%s): %s", consulta, exc)
            return []

        normalizados: list[dict] = []
        for item in resultados or []:
            normalizados.append(
                {
                    "titulo": item.get("title", ""),
                    "url": item.get("href", item.get("url", "")),
                    "resumo": item.get("body", item.get("snippet", "")),
                }
            )
        self.logger.info("Busca web '%s' retornou %d resultado(s).", consulta, len(normalizados))
        return normalizados

    def _criar_motor(self):
        """Instancia o motor de busca conforme BUSCA_WEB_PROVIDER."""
        if self.config.busca_web_provider in ("", "none", "off", "desligado"):
            return None
        try:
            from ddgs import DDGS  # pacote recomendado

            self.logger.info("Busca web habilitada via ddgs (DuckDuckGo).")
            return DDGS()
        except Exception:
            pass
        try:
            from duckduckgo_search import DDGS  # nome legado do pacote

            self.logger.info("Busca web habilitada via duckduckgo_search (legado).")
            return DDGS()
        except Exception:
            self.logger.warning(
                "Nenhum pacote de busca web instalado. Instale 'ddgs' ou defina "
                "BUSCA_WEB_PROVIDER=none. Agentes seguirão apenas com o catálogo local."
            )
            return None

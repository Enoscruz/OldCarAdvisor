"""Recuperação de conhecimento (RAG) que fundamenta os pareceres.

Antes de tocar o índice vetorial, a consulta passa por uma etapa de expansão:
termos do vocabulário do usuário são traduzidos para o vocabulário indexado
(ex.: "podre" -> ferrugem estrutural) e o estilo desejado entra na busca. O
resultado é fundido e deduplicado, servindo de contexto para os agentes.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import TYPE_CHECKING

from app.servicos.base_service import BaseService
from app.servicos.config import Config

if TYPE_CHECKING:  # evita carregar Chroma em quem só precisa formatar trechos
    from app.servicos.vetor_service import VetorService

# Tradução do vocabulário do usuário para os termos presentes na base indexada.
EXPANSOES: dict[str, tuple[str, ...]] = {
    "podre": ("ferrugem", "corrosao", "estrutural", "longarina"),
    "ferrugem": ("corrosao", "estrutural", "longarina", "assoalho"),
    "batida": ("estrutural", "longarina", "alinhamento", "chassi"),
    "peca": ("reposicao", "aftermarket", "lataria", "acabamento"),
    "pecas": ("reposicao", "aftermarket", "lataria", "acabamento"),
    "motor": ("swap", "mecanica", "cofre", "potencia"),
    "turbo": ("potencia", "swap", "motor"),
    "preco": ("orcamento", "fipe", "bolha", "custo", "build"),
    "barato": ("custo", "orcamento", "viavel"),
    "baixo": ("rebaixado", "suspensao", "stance"),
    "eletrica": ("injecao", "modulo", "chicote"),
    "tracao": ("rwd", "awd", "fwd", "diferencial"),
}


def formatar_trechos(trechos: list[dict]) -> str:
    """Serializa os trechos recuperados no bloco lido pelo LLM."""
    if not trechos:
        return "Nenhum trecho recuperado."
    return "\n\n".join(
        f"[{trecho.get('fonte', '?')}]\n{trecho.get('trecho', '')}" for trecho in trechos
    )


def chave_trecho(trecho: dict) -> str:
    """Chave estável que identifica um trecho na deduplicação."""
    return f"{trecho.get('fonte', '')}\n{str(trecho.get('trecho', ''))[:120]}"


def acumular_conhecimento(estado: dict, trechos: list[dict]) -> None:
    """Soma os trechos ao histórico da consulta, sem repetições."""
    acumulado = estado.setdefault("conhecimento", [])
    existentes = {chave_trecho(item) for item in acumulado}
    for trecho in trechos:
        chave = chave_trecho(trecho)
        if chave not in existentes:
            acumulado.append(trecho)
            existentes.add(chave)


class RecuperacaoService(BaseService):
    """Recupera contexto da base vetorial a partir da pergunta do usuário."""

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        vetor_service: VetorService,
    ) -> None:
        super().__init__(config, logger)
        self._vetor = vetor_service

    def expandir(self, consulta: str) -> list[str]:
        """Reescreve a consulta somando sinônimos do domínio automotivo."""
        tokens = set(self._tokens(consulta))
        equivalencias: set[str] = set()
        for token in tokens:
            equivalencias.update(EXPANSOES.get(token, ()))
        variantes = [consulta.strip()]
        novos = sorted(equivalencias - tokens)
        if novos:
            variantes.append(" ".join(novos))
        return variantes

    def recuperar(
        self,
        consulta: str,
        k: int | None = None,
        filtro: dict | None = None,
    ) -> list[dict]:
        """Busca por todas as variantes da consulta e devolve trechos únicos.

        Falhas de índice/base não interrompem a consultoria: o RAG é um
        reforço, então o erro é registrado e a análise segue sem contexto.
        """
        if not consulta.strip():
            return []
        limite = k or self.config.rag_k
        vistos: dict[str, dict] = {}
        try:
            for variante in self.expandir(consulta):
                for documento in self._vetor.buscar(variante, k=limite, filtro=filtro):
                    trecho = {
                        "fonte": str(documento.metadata.get("fonte", "?")),
                        "tipo": str(documento.metadata.get("tipo", "")),
                        "trecho": documento.page_content.strip(),
                    }
                    vistos.setdefault(chave_trecho(trecho), trecho)
        except Exception as exc:
            self.logger.warning("Falha na recuperação vetorial: %s", exc)
            return list(vistos.values())
        self.logger.info("RAG recuperou %d trecho(s) único(s).", len(vistos))
        return list(vistos.values())[:limite]

    @staticmethod
    def _tokens(texto: str) -> list[str]:
        normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
        return re.findall(r"[a-z0-9]+", normalizado.lower())

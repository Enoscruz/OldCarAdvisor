"""LLM-as-judge: avaliação subjetiva do veredito segundo uma rubrica.

As verificações de `metricas.py` checam o que é objetivamente certo: briefing
extraído, ramificação correta do grafo, invariantes das notas. Elas não dizem
se a recomendação é *boa*. Este módulo cobre essa lacuna pedindo a um modelo
que pontue o veredito em quatro critérios.

Como depende de um modelo real, a etapa é opcional e se declara indisponível no
modo mock: seria desonesto atribuir nota de qualidade a um texto simulado.
"""

from __future__ import annotations

import json
import logging
import re

from app.servicos.config import Config
from app.servicos.gemini_service import GeminiService
from app.servicos.prompt_service import PromptService

CRITERIOS = ("clareza", "honestidade", "personalizacao", "acionabilidade")


class JuizLLM:
    """Pontua a qualidade subjetiva da consultoria usando o modelo configurado."""

    SYSTEM_PROMPT = (
        "Você é um avaliador rigoroso de consultorias automotivas. "
        "Pontue a resposta apenas com base no pedido do usuário e nos dados "
        "fornecidos e responda exclusivamente no formato JSON pedido."
    )

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        prompt_service: PromptService,
        gemini_service: GeminiService,
    ) -> None:
        self._config = config
        self._logger = logger
        self._prompt_service = prompt_service
        self._gemini_service = gemini_service

    @property
    def disponivel(self) -> bool:
        return self._config.gemini_modo != "mock"

    def avaliar(self, pergunta: str, estado: dict) -> dict | None:
        """Devolve {'notas', 'media', 'justificativa'} ou None se indisponível."""
        if not self.disponivel:
            self._logger.info(
                "Juiz LLM ignorado: modo '%s' não permite julgar a qualidade.",
                self._config.gemini_modo,
            )
            return None

        prompt = self._prompt_service.preencher(
            "juiz",
            pergunta=pergunta,
            estilo=str(estado.get("estilo") or "GERAL"),
            orcamento=self._formatar_moeda(estado.get("orcamento")),
            tabela=str(estado.get("contexto") or ""),
            resposta=str(estado.get("resposta") or ""),
        )
        try:
            bruto = self._gemini_service.gerar(prompt, self.SYSTEM_PROMPT)
        except Exception as exc:
            self._logger.warning("Juiz LLM falhou na avaliação: %s", exc)
            return None
        return self._interpretar(bruto)

    @staticmethod
    def _interpretar(bruto: str) -> dict | None:
        """Extrai o JSON da resposta do modelo; ignora saída fora do formato."""
        match = re.search(r"\{.*\}", bruto, re.DOTALL)
        if not match:
            return None
        try:
            dados = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

        notas: dict[str, float] = {}
        for criterio in CRITERIOS:
            if criterio in dados:
                notas[criterio] = round(max(0.0, min(10.0, float(dados[criterio]))), 1)
        if not notas:
            return None

        return {
            "notas": notas,
            "media": round(sum(notas.values()) / len(notas), 2),
            "justificativa": str(dados.get("justificativa", "")).strip(),
        }

    @staticmethod
    def _formatar_moeda(valor: float | None) -> str:
        if not valor:
            return "não informado"
        return f"R$ {valor:,.0f}".replace(",", ".")

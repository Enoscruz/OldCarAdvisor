"""Implementação offline do Gemini para desenvolvimento local.

Simula as respostas dos agentes sem chamadas ao Vertex AI. Cada parecer é
derivado dos dados estruturados que o agente já produziu (a tabela de notas),
garantindo uma consultoria coerente mesmo sem credenciais de nuvem.
"""

from __future__ import annotations

import logging
import re

from app.servicos.base_service import BaseService
from app.servicos.config import Config

# Marcadores de cada template -> préâmbulo simulado.
PAREceres = {
    "## Notas de engenharia": "Análise técnica (modo offline):",
    "## Notas financeiras": "Análise financeira (modo offline):",
    "## Notas de peças": "Nota de viabilidade de peças (modo offline):",
    "## Relatos de crônicos": "Relatos de crônicos (modo offline):",
    "## Consolidado por candidato": "Consultoria consolidada (modo offline):",
}


class GeminiMockService(BaseService):
    """Simula respostas do Gemini sem chamadas ao Vertex AI."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self.logger.info("Gemini em modo MOCK — consultoria simulada localmente.")

    def gerar(self, prompt: str, system_prompt: str = "") -> str:
        """Gera texto simulado a partir do bloco de dados presente no prompt."""
        rodape = (
            "Esta é uma saída simulada (GEMINI_MODO=mock). Configure "
            "GEMINI_MODO=vertex e as credenciais GCP para a análise real."
        )
        for marcador, preambulo in PAREceres.items():
            if marcador in prompt:
                partes = [f"{preambulo}\n\n{self._extrair_bloco(prompt, marcador)}"]
                conhecimento = self._extrair_conhecimento(prompt)
                if conhecimento:
                    partes.append(f"Fundamentação (base de conhecimento, RAG):\n{conhecimento}")
                partes.append(rodape)
                return "\n\n".join(partes)

        pergunta = self._extrair_campo(prompt, "Pedido do usuário") or ""
        return (
            f"[MOCK] Resposta simulada para: {pergunta or 'solicitação não identificada'}. "
            "Configure GEMINI_MODO=vertex e credenciais GCP para respostas reais."
        )

    def gerar_sql(self, prompt: str, system_prompt: str = "") -> str:
        """Mantido por compatibilidade com módulos legados do fluxo comercial."""
        return "SELECT TOP 20 * FROM catalogo_carros"

    @staticmethod
    def _extrair_campo(prompt: str, rotulo: str) -> str:
        padrao = rf"##\s*{re.escape(rotulo)}\s*\n(.*?)(?:\n##|\Z)"
        match = re.search(padrao, prompt, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extrair_bloco(prompt: str, marcador: str) -> str:
        if marcador not in prompt:
            return ""
        return prompt.split(marcador, 1)[1].split("\n##", 1)[0].strip()

    @classmethod
    def _extrair_conhecimento(cls, prompt: str) -> str:
        """Trecho da base vetorial que fundamentaria a resposta real."""
        marcador = "## Conhecimento recuperado (RAG)"
        if marcador not in prompt:
            return ""
        bloco = prompt.split(marcador, 1)[1].split("\n## Nível de acesso", 1)[0].strip()
        if not bloco or bloco == "Nenhum trecho recuperado.":
            return ""
        return bloco if len(bloco) <= 700 else f"{bloco[:700].rstrip()}…"

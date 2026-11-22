"""Agente Engenheiro — análise técnica e potencial dinâmico do chassi.

Avalia tração, peso, suspensão, tamanho do cofre e potencial de swap para
validar se a plataforma combina com o estilo desejado (ex.: tração traseira
para Drift/Hot Rod, cofre amplo para swap).
"""

from __future__ import annotations

import logging

from app.agentes.agente_especialista import AgenteEspecialista
from app.modelos.estado import Estado
from app.servicos.config import Config
from app.servicos.gemini_service import GeminiService
from app.servicos.prompt_service import PromptService
from app.servicos.recuperacao_service import RecuperacaoService

# Aderência de tração por estilo (0-10).
TRACAO_POR_ESTILO: dict[str, dict[str, float]] = {
    "DRIFT": {"RWD": 10, "AWD": 7, "FWD": 2},
    "HOT_ROD": {"RWD": 10, "AWD": 6, "FWD": 3},
    "TURBO": {"FWD": 8, "RWD": 9, "AWD": 6},
    "STANCE": {"RWD": 9, "AWD": 9, "FWD": 6},
    "EURO": {"FWD": 8, "AWD": 9, "RWD": 8},
    "RESTOMOD": {"RWD": 9, "AWD": 8, "FWD": 7},
    "OFF_ROAD": {"AWD": 10, "RWD": 7, "FWD": 3},
    "GERAL": {"RWD": 8, "AWD": 8, "FWD": 7},
}
SCORE_COFRE = {"amplo": 10.0, "medio": 7.0, "estreito": 4.0}
SCORE_SWAP = {"alto": 10.0, "medio": 6.0, "baixo": 3.0}


class EngenheiroAgent(AgenteEspecialista):
    """Especialista em viabilidade técnica/dinâmica do projeto."""

    NOME = "Agente Engenheiro"
    CHAVE = "tecnico"
    TEMPLATE = "engenheiro"
    TERMOS_RAG = "engenharia tração suspensão cofre motor swap chassi estilo customização"
    SYSTEM_PROMPT = (
        "Você é engenheiro automotivo especialista em preparação de clássicos. "
        "Analise tração, peso, suspensão, cofre do motor e potencial de swap. "
        "Seja técnico, honesto sobre limitações e objetivo."
    )

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        prompt_service: PromptService,
        gemini_service: GeminiService,
        recuperacao_service: RecuperacaoService | None = None,
    ) -> None:
        super().__init__(config, logger, prompt_service, gemini_service, recuperacao_service)

    def _avaliar(self, candidato: dict, estado: Estado, fontes: list[str]) -> tuple[float, str]:
        estilo = (estado.get("estilo") or "GERAL").upper()
        tracao = str(candidato.get("tracao", "")).upper()
        cofre = str(candidato.get("cofre_motor", "")).lower()
        swap = str(candidato.get("potencial_swap", "")).lower()
        peso = self._extrair_numero(candidato, "peso_kg") or 0

        nota_tracao = TRACAO_POR_ESTILO.get(estilo, TRACAO_POR_ESTILO["GERAL"]).get(tracao, 5.0)
        nota_cofre = SCORE_COFRE.get(cofre, 5.0)
        nota_swap = SCORE_SWAP.get(swap, 5.0)
        nota_peso = 10.0 if peso and peso < 950 else (7.0 if peso and peso < 1200 else 5.0)

        nota = 0.40 * nota_tracao + 0.25 * nota_cofre + 0.25 * nota_swap + 0.10 * nota_peso
        motivo = (
            f"tração {tracao or 'n/d'} para {estilo}, cofre {cofre or 'n/d'}, "
            f"swap {swap or 'n/d'}, peso {int(peso) if peso else 'n/d'} kg"
        )
        return round(nota, 1), motivo

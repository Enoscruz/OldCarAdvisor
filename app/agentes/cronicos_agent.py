"""Agente Caçador de Crônicos — histórico, fóruns e fragilidades ocultas.

Identifica problemas crônicos que destroem projetos de modificação (ferrugem
estrutural, trincas de túnel/longarina, elétrica problemática em importados
dos anos 90). Usa o catálogo local e, quando online, relatos de fóruns.
"""

from __future__ import annotations

import logging

from app.agentes.agente_especialista import AgenteEspecialista
from app.modelos.estado import Estado
from app.servicos.busca_web_service import BuscaWebService
from app.servicos.config import Config
from app.servicos.gemini_service import GeminiService
from app.servicos.prompt_service import PromptService
from app.servicos.recuperacao_service import RecuperacaoService

SCORE_FERRUGEM = {"baixo": 10.0, "medio": 6.0, "alto": 3.0}
SCORE_ELETRICA = {"simples": 9.0, "media": 6.0, "complexa": 3.0}


class CronicosAgent(AgenteEspecialista):
    """Especialista em problemas crônicos e riscos estruturais."""

    NOME = "Agente Caçador de Crônicos"
    CHAVE = "cronicos"
    TEMPLATE = "cronicos"
    TERMOS_RAG = "crônicos ferrugem estrutural longarina elétrica inspeção histórico falhas"
    SYSTEM_PROMPT = (
        "Você investiga problemas crônicos de carros clássicos com base em "
        "histórico de oficinas e fóruns. Seja honesto sobre ferrugem estrutural, "
        "trincas e elétrica problemática, apontando o risco para o projeto."
    )

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        prompt_service: PromptService,
        gemini_service: GeminiService,
        busca_web_service: BuscaWebService,
        recuperacao_service: RecuperacaoService | None = None,
    ) -> None:
        super().__init__(config, logger, prompt_service, gemini_service, recuperacao_service)
        self._busca_web = busca_web_service

    def _avaliar(self, candidato: dict, estado: Estado, fontes: list[str]) -> tuple[float, str]:
        ferrugem = str(candidato.get("risco_ferrugem", "")).lower()
        eletrica = str(candidato.get("eletrica", "")).lower()
        cronicos = str(candidato.get("cronicos_conhecidos", "")).strip()

        nota_ferrugem = SCORE_FERRUGEM.get(ferrugem, 5.0)
        nota_eletrica = SCORE_ELETRICA.get(eletrica, 5.0)
        nota = 0.55 * nota_ferrugem + 0.45 * nota_eletrica

        resultados = self._busca_web.pesquisar(
            f"{candidato.get('montadora', '')} {candidato.get('modelo', '')} "
            f"problemas crônicos ferrugem fórum preparação"
        )
        if resultados:
            fontes.append(f"Fóruns {candidato.get('modelo')}: {len(resultados)} relato(s)")

        nota = max(0.0, min(10.0, nota))
        motivo = f"ferrugem {ferrugem or 'n/d'}, elétrica {eletrica or 'n/d'}"
        if cronicos:
            motivo = f"{motivo}; {cronicos}"
        return round(nota, 1), motivo

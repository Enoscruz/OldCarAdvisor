"""Agente de Aftermarket — disponibilidade de peças e componentes.

Mapeia o ecossistema de reposição e performance a partir do catálogo local e,
quando online, complementa com busca na internet. Emite uma "Nota de
Viabilidade de Peças": carros que dependem de lataria rara ou mecânica extinta
são penalizados para evitar projetos que param no meio.
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

SCORE_PECA = {"facil": 10.0, "media": 6.0, "raras": 2.0, "rara": 2.0}
SCORE_IMPORTADO = {"sim": 10.0, "limitado": 5.0, "nao": 2.0, "não": 2.0}


class AftermarketAgent(AgenteEspecialista):
    """Especialista em disponibilidade de peças nacionais e importadas."""

    NOME = "Agente de Aftermarket"
    CHAVE = "pecas"
    TEMPLATE = "aftermarket"
    TERMOS_RAG = "peças reposição lataria mecânica acabamento importado aftermarket raridade"
    SYSTEM_PROMPT = (
        "Você é especialista em aftermarket de carros clássicos no Brasil. "
        "Avalie disponibilidade de lataria, mecânica e itens importados e "
        "penalize modelos cujo projeto tende a ficar inacabado."
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
        lataria = str(candidato.get("pecas_lataria", "")).lower()
        mecanica = str(candidato.get("pecas_mecanica", "")).lower()
        importado = str(candidato.get("aftermarket_importado", "")).lower()

        nota_lataria = SCORE_PECA.get(lataria, 5.0)
        nota_mecanica = SCORE_PECA.get(mecanica, 5.0)
        nota_importado = SCORE_IMPORTADO.get(importado, 5.0)

        nota = 0.45 * nota_lataria + 0.45 * nota_mecanica + 0.10 * nota_importado

        # Complemento opcional via web (peças nacionais e importadas).
        resultados = self._busca_web.pesquisar(
            f"peças {candidato.get('montadora', '')} {candidato.get('modelo', '')} "
            f"lataria restomod brasil"
        )
        if resultados:
            fontes.append(f"Busca de peças {candidato.get('modelo')}: {len(resultados)} resultado(s)")
            if len(resultados) >= 3:
                nota = min(10.0, nota + 0.5)

        nota = max(0.0, min(10.0, nota))
        motivo = f"lataria {lataria or 'n/d'}, mecânica {mecanica or 'n/d'}, importado {importado or 'n/d'}"
        return round(nota, 1), motivo

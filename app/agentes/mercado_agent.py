"""Agente de Mercado — custo de entrada, orçamento e "bolha de preço".

Cruza o preço de entrada do clássico (catálogo local, validado pela Tabela
FIPE quando disponível) com o orçamento total do usuário, sinaliza modelos
superfaturados e alerta quando o build estoura o que sobra do orçamento.
"""

from __future__ import annotations

import logging

from app.agentes.agente_especialista import AgenteEspecialista
from app.modelos.estado import Estado
from app.servicos.config import Config
from app.servicos.fipe_service import FipeService
from app.servicos.gemini_service import GeminiService
from app.servicos.prompt_service import PromptService
from app.servicos.recuperacao_service import RecuperacaoService


class MercadoAgent(AgenteEspecialista):
    """Especialista em viabilidade financeira e preço de mercado."""

    NOME = "Agente de Mercado"
    CHAVE = "mercado"
    TEMPLATE = "mercado"
    TERMOS_RAG = "mercado preço FIPE bolha orçamento custo de build valorização"
    SYSTEM_PROMPT = (
        "Você é um analista de mercado de carros clássicos no Brasil. "
        "Avalie custo de entrada, bolha de preço e encaixe no orçamento. "
        "Seja realista e alerte sobre superfaturamento."
    )
    LIMIAR_BOLHA = 0.15  # 15% acima da referência FIPE já é considerado bolha

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        prompt_service: PromptService,
        gemini_service: GeminiService,
        fipe_service: FipeService,
        recuperacao_service: RecuperacaoService | None = None,
    ) -> None:
        super().__init__(config, logger, prompt_service, gemini_service, recuperacao_service)
        self._fipe_service = fipe_service

    def _avaliar(self, candidato: dict, estado: Estado, fontes: list[str]) -> tuple[float, str]:
        orcamento = estado.get("orcamento") or 0.0
        entrada = self._extrair_numero(candidato, "preco_entrada_medio") or 0.0
        build = self._extrair_numero(candidato, "custo_build_estimado") or 0.0
        referencia = self._extrair_numero(candidato, "valor_fipe_ref") or 0.0

        # Valida o preço de entrada com a FIPE real quando disponível.
        fipe = self._fipe_service.buscar_preco_por_nome(
            f"{candidato.get('montadora', '')} {candidato.get('modelo', '')}".strip()
        )
        if fipe.get("valor_numerico"):
            referencia = fipe["valor_numerico"]
            fontes.append(f"FIPE: {fipe.get('modelo_fipe', candidato.get('modelo'))} — {fipe.get('valor_texto')}")

        bolha = (entrada / referencia - 1) if referencia else 0.0
        superfaturado = bolha > self.LIMIAR_BOLHA

        if not orcamento:
            nota = 8.0 if not superfaturado else 5.0
        else:
            fracao = entrada / orcamento
            # Ideal: entrada consome até a fração configurada do orçamento.
            if fracao <= self.config.fracao_entrada_orcamento:
                nota = 10.0
            elif fracao >= 1.0:
                nota = 0.0
            else:
                excesso = (fracao - self.config.fracao_entrada_orcamento) / (
                    1.0 - self.config.fracao_entrada_orcamento
                )
                nota = 10.0 * (1.0 - excesso)
            if superfaturado:
                nota -= 2.5
            if orcamento and entrada + build > orcamento:
                nota -= 1.5

        nota = max(0.0, min(10.0, nota))
        partes = [f"entrada R$ {entrada:,.0f}".replace(",", ".")]
        if orcamento:
            partes.append(f"{entrada / orcamento * 100:.0f}% do orçamento")
        if referencia:
            partes.append(
                f"bolha {bolha * 100:+.0f}% vs FIPE" + (" (superfaturado)" if superfaturado else "")
            )
        if orcamento and entrada + build > orcamento:
            partes.append("build estoura o orçamento")
        return round(nota, 1), ", ".join(partes)

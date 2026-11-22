"""Agente Consultor — sintetiza os quatro especialistas e recomenda.

Consolida as notas de engenharia, mercado, aftermarket e crônicos em uma
nota final ponderada, ranqueia os candidatos e redige a consultoria final
hiper-personalizada (o "veredito" de compra). Também consulta a base vetorial
para ancorar a recomendação no conhecimento técnico indexado.
"""

from __future__ import annotations

import logging

from app.modelos.estado import Estado
from app.servicos.base_service import BaseService
from app.servicos.config import Config
from app.servicos.gemini_service import GeminiService
from app.servicos.prompt_service import PromptService
from app.servicos.recuperacao_service import (
    RecuperacaoService,
    acumular_conhecimento,
    formatar_trechos,
)

# Pesos do veredito final (somam 1.0).
PESOS = {"tecnico": 0.30, "mercado": 0.25, "pecas": 0.25, "cronicos": 0.20}
ROTULOS = {
    "tecnico": "Engenharia",
    "mercado": "Mercado",
    "pecas": "Aftermarket",
    "cronicos": "Crônicos",
}


class ConsultorAgent(BaseService):
    """Consolida os pareceres e produz a recomendação final."""

    SYSTEM_PROMPT = (
        "Você é o consultor-chefe de compra de clássicos para customização. "
        "Consolide engenharia, mercado, aftermarket e crônicos em um veredito "
        "claro, honesto e hiper-personalizado. Aponte o melhor carro, os riscos "
        "e um plano de ação objetivo."
    )

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        prompt_service: PromptService,
        gemini_service: GeminiService,
        recuperacao_service: RecuperacaoService | None = None,
    ) -> None:
        super().__init__(config, logger)
        self._prompt_service = prompt_service
        self._gemini_service = gemini_service
        self._recuperacao = recuperacao_service

    def executar(self, estado: Estado) -> Estado:
        """Calcula nota final, ranqueia e redige a recomendação."""
        avaliacoes = estado.get("avaliacoes", [])
        if not avaliacoes:
            estado["resposta"] = (
                "Não encontrei clássicos compatíveis com o orçamento e o estilo informados. "
                "Tente aumentar o orçamento ou descrever melhor o projeto desejado."
            )
            estado["recomendacao"] = estado["resposta"]
            return estado

        for avaliacao in avaliacoes:
            avaliacao["nota_final"] = self._nota_final(avaliacao)

        ranking = sorted(avaliacoes, key=lambda a: a.get("nota_final", 0), reverse=True)
        estado["ranking"] = ranking
        estado["nota_viabilidade"] = ranking[0].get("nota_final", 0.0) if ranking else 0.0

        tabela = self._montar_tabela(ranking)
        estado["contexto"] = tabela

        trechos = self._recuperar_conhecimento(estado, ranking)
        acumular_conhecimento(estado, trechos)

        prompt = self._prompt_service.preencher(
            "consultor",
            pergunta=estado.get("pergunta", ""),
            estilo=estado.get("estilo", "GERAL"),
            orcamento=self._formatar_orcamento(estado.get("orcamento")),
            regiao=estado.get("regiao") or "não informada",
            tabela=tabela,
            nivel=estado.get("nivel", "B"),
            conhecimento=formatar_trechos(trechos),
        )
        try:
            resposta = self._gemini_service.gerar(prompt, self.SYSTEM_PROMPT)
        except Exception as exc:
            self.logger.warning("Falha ao redigir recomendação final: %s", exc)
            resposta = ""
        estado["recomendacao"] = resposta.strip() or tabela
        estado["resposta"] = estado["recomendacao"]
        return estado

    # ------------------------------------------------------------------
    def _recuperar_conhecimento(self, estado: Estado, ranking: list[dict]) -> list[dict]:
        """Contexto RAG do veredito: estilo, finalistas e termos de decisão."""
        if self._recuperacao is None:
            return []
        finalistas = " ".join(str(item.get("modelo", "")) for item in ranking[:2])
        consulta = " ".join(
            parte
            for parte in (
                estado.get("pergunta", ""),
                estado.get("estilo", ""),
                "recomendação de compra veredito plano de ação riscos",
                finalistas,
            )
            if parte
        )
        return self._recuperacao.recuperar(consulta)

    @staticmethod
    def _nota_final(avaliacao: dict) -> float:
        total = 0.0
        for chave, peso in PESOS.items():
            bloco = avaliacao.get(chave) or {}
            total += peso * float(bloco.get("nota", 0.0))
        return round(total, 1)

    @staticmethod
    def _montar_tabela(ranking: list[dict]) -> str:
        linhas = ["Modelo | Engenharia | Mercado | Aftermarket | Crônicos | Nota final"]
        for item in ranking:
            colunas = [
                str(item.get("modelo", "?")),
                f"{(item.get('tecnico') or {}).get('nota', 0):.1f}",
                f"{(item.get('mercado') or {}).get('nota', 0):.1f}",
                f"{(item.get('pecas') or {}).get('nota', 0):.1f}",
                f"{(item.get('cronicos') or {}).get('nota', 0):.1f}",
                f"{item.get('nota_final', 0):.1f}",
            ]
            linhas.append(" | ".join(colunas))
        return "\n".join(linhas)

    @staticmethod
    def _formatar_orcamento(orcamento: float | None) -> str:
        if not orcamento:
            return "não informado"
        return f"R$ {orcamento:,.0f}".replace(",", ".")

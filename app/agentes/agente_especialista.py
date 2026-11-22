"""Base comum dos agentes especialistas da consultoria de clássicos.

Cada especialista avalia o shortlist de candidatos com uma nota (0-10) e um
motivo curto, acumula o resultado em `estado["avaliacoes"]` e redige um
parecer em linguagem natural via LLM. A nota e o motivo são determinísticos
(regras de engenharia/mercado), garantindo resultado mesmo offline; o LLM
apenas transforma os números em texto.

Antes de redigir, o agente consulta a base vetorial (RAG) com uma pergunta
enriquecida pelo vocabulário do seu domínio. Os trechos recuperados entram no
prompt como fundamentação e ficam registrados em `estado["conhecimento"]`,
permitindo auditar em que conhecimento cada parecer se apoiou.
"""

from __future__ import annotations

import logging

from app.modelos.estado import Estado, ParecerAgente
from app.servicos.base_service import BaseService
from app.servicos.config import Config
from app.servicos.gemini_service import GeminiService
from app.servicos.prompt_service import PromptService
from app.servicos.recuperacao_service import (
    RecuperacaoService,
    acumular_conhecimento,
    formatar_trechos,
)


class AgenteEspecialista(BaseService):
    """Esqueleto de um agente que pontua candidatos e emite parecer."""

    NOME = "Agente"
    CHAVE = "geral"
    TEMPLATE = "agente"
    TERMOS_RAG = ""
    SYSTEM_PROMPT = (
        "Você é um consultor técnico de carros clássicos para customização. "
        "Baseie-se apenas nos dados fornecidos e seja direto e honesto."
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

    # ------------------------------------------------------------------
    def executar(self, estado: Estado) -> Estado:
        """Pontua cada candidato, registra o parecer e segue o fluxo."""
        candidatos = estado.get("candidatos", [])
        avaliacoes = estado.setdefault("avaliacoes", [])
        fontes: list[str] = []
        linhas: list[str] = []
        notas: list[float] = []

        for indice, candidato in enumerate(candidatos):
            if indice >= len(avaliacoes):
                break
            nota, motivo = self._avaliar(candidato, estado, fontes)
            avaliacoes[indice][self.CHAVE] = {"nota": round(nota, 1), "motivo": motivo}
            notas.append(nota)
            linhas.append(f"- {candidato.get('modelo', '?')} ({candidato.get('montadora', '')}): nota {nota:.1f} — {motivo}")

        trechos = self._recuperar_conhecimento(estado)
        fontes.extend(f"RAG: {trecho['fonte']}" for trecho in trechos)

        media = round(sum(notas) / len(notas), 1) if notas else 0.0
        tabela = "\n".join(linhas) or "Nenhum candidato no shortlist."
        parecer = self._redigir(estado, tabela, trechos)
        estado.setdefault("pareceres", {})[self.NOME] = ParecerAgente(
            agente=self.NOME,
            nota=media,
            resumo=f"Média de {media}/10 entre {len(notas)} candidato(s).",
            parecer=parecer,
            fontes=fontes,
        )
        acumular_conhecimento(estado, trechos)
        return estado

    # ------------------------------------------------------------------
    def _avaliar(self, candidato: dict, estado: Estado, fontes: list[str]) -> tuple[float, str]:
        """Retorna (nota 0-10, motivo). Implementado por cada especialista."""
        raise NotImplementedError

    def _consulta_rag(self, estado: Estado) -> str:
        """Consulta enriquecida com o vocabulário do domínio do agente."""
        modelos = " ".join(str(c.get("modelo", "")) for c in estado.get("candidatos", []))
        return " ".join(
            parte
            for parte in (
                estado.get("pergunta", ""),
                estado.get("estilo", ""),
                self.TERMOS_RAG,
                modelos,
            )
            if parte
        )

    def _recuperar_conhecimento(self, estado: Estado) -> list[dict]:
        if self._recuperacao is None:
            return []
        return self._recuperacao.recuperar(self._consulta_rag(estado))

    def _redigir(self, estado: Estado, tabela: str, trechos: list[dict]) -> str:
        prompt = self._prompt_service.preencher(
            self.TEMPLATE,
            pergunta=estado.get("pergunta", ""),
            estilo=estado.get("estilo", "GERAL"),
            orcamento=self._formatar_orcamento(estado.get("orcamento")),
            tabela=tabela,
            nivel=estado.get("nivel", "B"),
            conhecimento=formatar_trechos(trechos),
        )
        try:
            texto = self._gemini_service.gerar(prompt, self.SYSTEM_PROMPT)
        except Exception as exc:  # nunca derruba a consultoria por falha de LLM
            self.logger.warning("Falha ao redigir parecer de %s: %s", self.NOME, exc)
            texto = ""
        return texto.strip() or tabela

    # ------------------------------------------------------------------
    @staticmethod
    def _formatar_orcamento(orcamento: float | None) -> str:
        if not orcamento:
            return "não informado"
        return f"R$ {orcamento:,.0f}".replace(",", ".")

    @staticmethod
    def _extrair_numero(candidato: dict, chave: str) -> float | None:
        valor = candidato.get(chave)
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None

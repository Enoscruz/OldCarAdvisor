"""Estado compartilhado da State Machine e enums do domínio automotivo.

O projeto deixou de ser um copiloto comercial e passou a ser uma plataforma
multi-agente de consultoria de compra de clássicos para customização. Este
módulo concentra o vocabulário do domínio (estilos de projeto, níveis de
acesso) e o `Estado`, que é a fonte única de verdade do fluxo de execução.
"""

from enum import StrEnum
from typing import NotRequired, TypedDict

import pandas as pd


class EstiloCustomizacao(StrEnum):
    """Estilos de customização reconhecidos pela plataforma."""

    RESTOMOD = "RESTOMOD"
    HOT_ROD = "HOT_ROD"
    STANCE = "STANCE"
    EURO = "EURO"
    TURBO = "TURBO"
    DRIFT = "DRIFT"
    OFF_ROAD = "OFF_ROAD"
    GERAL = "GERAL"


class NivelAcesso(StrEnum):
    """Níveis de acesso definidos na política de acesso (rls.xlsx)."""

    B = "B"
    A = "A"
    GOD = "GOD"


# Mantido por compatibilidade com os módulos legados ainda presentes no
# repositório (representam o fluxo comercial anterior).
class Intencao(StrEnum):
    CONSULTA = "CONSULTA"
    RAG = "RAG"
    ANALYTICS = "ANALYTICS"


class ParecerAgente(TypedDict, total=False):
    """Resultado consolidado de um agente especialista."""

    agente: str
    nota: float
    resumo: str
    parecer: str
    fontes: list[str]


class Estado(TypedDict, total=False):
    """Fonte de verdade única do fluxo de consultoria.

    Reúne o briefing do usuário, o shortlist de candidatos, o parecer de cada
    agente especialista e a recomendação final do consultor.
    """

    # --- Entrada ---
    pergunta: str
    email: str
    nivel: str

    # --- Briefing extraído do pedido do usuário ---
    orcamento: float
    estilo: str
    regiao: str
    restricoes: str

    # --- Pipeline multi-agente ---
    candidatos: list[dict]
    avaliacoes: list[dict]
    pareceres: dict[str, ParecerAgente]
    ranking: list[dict]
    nota_viabilidade: float
    recomendacao: str
    # Trechos da base vetorial recuperados durante a consultoria (RAG).
    conhecimento: list[dict]

    # --- Controle do grafo de decisão (LangGraph) ---
    # Caminho percorrido no grafo, na ordem de execução (fluxo de pensamento).
    fluxo: list[str]
    # Indica se há base vetorial disponível para o refinamento de busca.
    recuperacao_ativa: bool
    # Quantas vezes o grafo já tentou refazer a busca por contexto.
    tentativas_recuperacao: int

    # --- Saídas / telemetria (também consumidas pela governança) ---
    agente: str
    intencao: str
    contexto: str
    resposta: str
    sql: str
    dados: pd.DataFrame
    erro: NotRequired[str]

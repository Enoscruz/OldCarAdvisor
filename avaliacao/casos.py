"""Casos de avaliação: pedidos realistas e expectativas verificáveis.

Cada caso é um pedido de consultoria acompanhado do que o resultado **precisa**
ter para ser considerado correto. As expectativas são checadas de forma
determinística (sem LLM), o que permite rodar a suíte no CI, offline e sem
credenciais de nuvem.

Os casos cobrem as três ramificações do grafo (caminho completo, encerramento
por orçamento insuficiente e acesso negado), além de regras de negócio que já
quebraram no passado — como a prioridade entre estilos ("restomod euro" deve
ser lido como RESTOMOD) e a extração de orçamento com sufixo "mil".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Caso:
    """Um pedido de consultoria e as expectativas sobre o estado final."""

    nome: str
    pergunta: str
    email: str = "admin@oldcaradvisor.com"

    # Briefing esperado.
    estilo_esperado: str | None = None
    orcamento_esperado: float | None = None

    # Caminho esperado no grafo de decisão (LangGraph).
    fluxo_obrigatorio: tuple[str, ...] = ()
    fluxo_proibido: tuple[str, ...] = ()
    fluxo_final: str | None = None

    # Resultado esperado.
    exige_ranking: bool = False
    exige_conhecimento: bool = False
    exige_erro: bool = False
    primeira_escolha: str | None = None
    trecho_esperado: str | None = None


CASOS: tuple[Caso, ...] = (
    Caso(
        nome="hot_rod_opala_completo",
        pergunta="Tenho R$ 90 mil para um Opala hot rod no Sudeste.",
        estilo_esperado="HOT_ROD",
        orcamento_esperado=90000.0,
        fluxo_obrigatorio=(
            "acesso", "briefing", "catalogo", "engenheiro",
            "mercado", "aftermarket", "cronicos", "consultor",
        ),
        fluxo_proibido=("sem_candidatos", "aviso_orcamento"),
        fluxo_final="consultor",
        exige_ranking=True,
        exige_conhecimento=True,
        primeira_escolha="Opala",
    ),
    Caso(
        nome="restomod_orcamento_insuficiente",
        pergunta="Quero um restomod com R$ 8 mil.",
        estilo_esperado="RESTOMOD",
        orcamento_esperado=8000.0,
        fluxo_obrigatorio=("acesso", "briefing", "catalogo", "engenheiro", "mercado", "aviso_orcamento"),
        fluxo_proibido=("aftermarket", "cronicos", "consultor"),
        fluxo_final="aviso_orcamento",
        trecho_esperado="n\u00e3o cobre",
    ),
    Caso(
        nome="turbo_de_rua_orcamento_medio",
        pergunta="Quero um cl\u00e1ssico para projeto turbo de rua, or\u00e7amento de R$ 60 mil.",
        estilo_esperado="TURBO",
        orcamento_esperado=60000.0,
        fluxo_obrigatorio=("engenheiro", "mercado", "consultor"),
        fluxo_final="consultor",
        exige_ranking=True,
        exige_conhecimento=True,
    ),
    Caso(
        nome="restomod_euro_prioriza_restomod",
        pergunta="Qual cl\u00e1ssico \u00e9 vi\u00e1vel para um restomod euro at\u00e9 R$ 120 mil?",
        estilo_esperado="RESTOMOD",
        orcamento_esperado=120000.0,
        fluxo_final="consultor",
        exige_ranking=True,
    ),
    Caso(
        nome="projeto_sem_estilo_declarado",
        pergunta="Tenho R$ 50 mil e quero come\u00e7ar um projeto de customiza\u00e7\u00e3o.",
        estilo_esperado="GERAL",
        orcamento_esperado=50000.0,
        fluxo_final="consultor",
        exige_ranking=True,
    ),
    Caso(
        nome="acesso_negado",
        pergunta="Quero um Opala hot rod com R$ 90 mil.",
        email="intruso@exemplo.com",
        fluxo_obrigatorio=("acesso",),
        fluxo_proibido=("briefing", "catalogo", "consultor"),
        fluxo_final="acesso",
        exige_erro=True,
    ),
)

NOMES = tuple(caso.nome for caso in CASOS)

"""Orquestração da consultoria multi-agente como grafo de estados (LangGraph).

Em vez de uma sequência fixa de chamadas, o fluxo é um grafo com nós e arestas
condicionais, o que permite decisões em tempo real:

    START -> acesso --(acesso negado)--------------------------> END
                     --(autorizado)--> briefing -> catalogo
    catalogo --(sem candidatos compatíveis)--> sem_candidatos --> END
             --(com candidatos)--> engenheiro -> mercado
    mercado --(orçamento não fecha a entrada de nenhum)--> aviso_orcamento --> END
            --(algo cabe)--> aftermarket -> cronicos
    cronicos --(líder com risco crônico e ainda há tentativa)--> refinar_busca
             --(risco aceitável / já tentou)--------------------> consultor --> END
    refinar_busca --> (reavalia a condição) ----------------> consultor --> END

As três decisões são reais, não decorativas:

1. encerra cedo quando o catálogo não tem nada compatível com estilo/orçamento;
2. encerra cedo quando nenhum candidato tem orçamento nem para a compra,
   evitando um ranking sem sentido;
3. quando o candidato líder tem o risco crônico como ponto fraco, refaz a
   busca na base vetorial com o foco nos problemas daquele modelo antes de
   fechar o veredito (uma única tentativa, para o loop não crescer).

O caminho percorrido fica em `estado["fluxo"]`, tornando auditável o raciocínio
do sistema (fluxo de pensamento e ação).
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.agentes.aftermarket_agent import AftermarketAgent
from app.agentes.consultor_agent import PESOS, ConsultorAgent
from app.agentes.cronicos_agent import CronicosAgent
from app.agentes.engenheiro_agent import EngenheiroAgent
from app.agentes.mercado_agent import MercadoAgent
from app.modelos.estado import Estado
from app.servicos.base_service import BaseService
from app.servicos.briefing_service import BriefingService
from app.servicos.catalogo_service import CatalogoService
from app.servicos.config import Config
from app.servicos.controle_acesso import ControleAcesso
from app.servicos.recuperacao_service import RecuperacaoService, acumular_conhecimento

SEM_CANDIDATOS = (
    "Não encontrei clássicos compatíveis com o orçamento e o estilo informados. "
    "Tente aumentar o orçamento ou descrever melhor o projeto desejado."
)


class Orquestrador(BaseService):
    """Compila e executa o grafo de decisão da consultoria de clássicos."""

    # Quantas vezes o grafo pode refazer a busca por contexto antes do veredito.
    LIMITE_REFINAMENTO = 1
    # Abaixo desta nota no agente de crônicos, o risco do líder é considerado
    # relevante o bastante para justificar uma busca dirigida.
    LIMIAR_RISCO_CRONICO = 6.0

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        controle_acesso: ControleAcesso,
        briefing_service: BriefingService,
        catalogo_service: CatalogoService,
        engenheiro_agent: EngenheiroAgent,
        mercado_agent: MercadoAgent,
        aftermarket_agent: AftermarketAgent,
        cronicos_agent: CronicosAgent,
        consultor_agent: ConsultorAgent,
        recuperacao_service: RecuperacaoService | None = None,
    ) -> None:
        super().__init__(config, logger)
        self._controle_acesso = controle_acesso
        self._briefing_service = briefing_service
        self._catalogo_service = catalogo_service
        self._engenheiro = engenheiro_agent
        self._mercado = mercado_agent
        self._aftermarket = aftermarket_agent
        self._cronicos = cronicos_agent
        self._consultor = consultor_agent
        self._recuperacao = recuperacao_service
        self._app = self._compilar()

    # ------------------------------------------------------------------
    def executar(self, pergunta: str, email: str) -> Estado:
        """Executa o grafo e devolve o estado consolidado da consultoria.

        Usa `stream` em vez de `invoke` por dois motivos: registrar o caminho
        percorrido no grafo e preservar o que já foi produzido caso um nó falhe
        no meio do fluxo.
        """
        inicial: Estado = {
            "pergunta": pergunta.strip(),
            "email": email.strip(),
            "agente": "Grafo de consultoria (LangGraph)",
            "intencao": "CONSULTORIA",
            "conhecimento": [],
            "tentativas_recuperacao": 0,
        }
        estado: Estado = dict(inicial)
        fluxo: list[str] = []
        try:
            for passo in self._app.stream(inicial, stream_mode="updates"):
                for nome, atualizacao in passo.items():
                    fluxo.append(nome)
                    if isinstance(atualizacao, dict):
                        estado.update(atualizacao)
        except Exception as exc:
            self.logger.exception("Erro no grafo de consultoria: %s", exc)
            estado["erro"] = str(exc)
            estado["resposta"] = f"Não foi possível concluir a consultoria: {exc}"

        estado["fluxo"] = fluxo
        self.logger.info("Fluxo executado: %s", " -> ".join(fluxo) or "(vazio)")
        return estado

    # ------------------------------------------------------------------
    # Montagem do grafo
    # ------------------------------------------------------------------
    def _compilar(self):
        grafo = StateGraph(Estado)
        grafo.add_node("acesso", self._no_acesso)
        grafo.add_node("briefing", self._no_briefing)
        grafo.add_node("catalogo", self._no_catalogo)
        grafo.add_node("sem_candidatos", self._no_sem_candidatos)
        grafo.add_node("engenheiro", self._engenheiro.executar)
        grafo.add_node("mercado", self._mercado.executar)
        grafo.add_node("aviso_orcamento", self._no_aviso_orcamento)
        grafo.add_node("aftermarket", self._aftermarket.executar)
        grafo.add_node("cronicos", self._cronicos.executar)
        grafo.add_node("refinar_busca", self._no_refinar_busca)
        grafo.add_node("consultor", self._consultor.executar)

        grafo.add_edge(START, "acesso")
        grafo.add_conditional_edges(
            "acesso",
            self._apos_acesso,
            {"briefing": "briefing", "encerrar": END},
        )
        grafo.add_edge("briefing", "catalogo")
        grafo.add_conditional_edges(
            "catalogo",
            self._apos_catalogo,
            {"especialistas": "engenheiro", "sem_candidatos": "sem_candidatos"},
        )
        grafo.add_edge("sem_candidatos", END)
        grafo.add_edge("engenheiro", "mercado")
        grafo.add_conditional_edges(
            "mercado",
            self._apos_mercado,
            {"continuar": "aftermarket", "aviso_orcamento": "aviso_orcamento"},
        )
        grafo.add_edge("aviso_orcamento", END)
        grafo.add_edge("aftermarket", "cronicos")
        grafo.add_conditional_edges(
            "cronicos",
            self._apos_cronicos,
            {"refinar_busca": "refinar_busca", "consultor": "consultor"},
        )
        grafo.add_conditional_edges(
            "refinar_busca",
            self._apos_cronicos,
            {"refinar_busca": "consultor", "consultor": "consultor"},
        )
        grafo.add_edge("consultor", END)
        return grafo.compile()

    # ------------------------------------------------------------------
    # Nós
    # ------------------------------------------------------------------
    def _no_acesso(self, estado: Estado) -> Estado:
        """Valida o e-mail na política de acesso (rls.xlsx)."""
        try:
            nivel = self._controle_acesso.validar(estado.get("email", ""))
            estado["nivel"] = nivel.value
            estado["recuperacao_ativa"] = self._recuperacao is not None
        except PermissionError as exc:
            self.logger.warning("Acesso negado: %s", exc)
            estado["erro"] = str(exc)
            estado["resposta"] = str(exc)
        return estado

    def _no_briefing(self, estado: Estado) -> Estado:
        """Extrai orçamento, estilo, região e restrições do pedido."""
        briefing = self._briefing_service.extrair(estado.get("pergunta", ""))
        estado["orcamento"] = briefing["orcamento"]
        estado["estilo"] = briefing["estilo"]
        estado["regiao"] = briefing["regiao"]
        estado["restricoes"] = briefing["restricoes"]
        return estado

    def _no_catalogo(self, estado: Estado) -> Estado:
        """Monta o shortlist de candidatos e as linhas de avaliação."""
        candidatos = self._catalogo_service.selecionar_candidatos(
            orcamento=estado.get("orcamento"),
            estilo=estado.get("estilo"),
            termo_livre=estado.get("pergunta", ""),
        )
        estado["candidatos"] = candidatos
        estado["avaliacoes"] = [self._avaliacao_base(candidato) for candidato in candidatos]
        return estado

    def _no_sem_candidatos(self, estado: Estado) -> Estado:
        """Encerra a consultoria sem gastar as quatro análises especialistas."""
        self.logger.info("Nenhum candidato compatível: encerrando sem pareceres.")
        estado["ranking"] = []
        estado["nota_viabilidade"] = 0.0
        estado["recomendacao"] = SEM_CANDIDATOS
        estado["resposta"] = SEM_CANDIDATOS
        return estado

    def _no_aviso_orcamento(self, estado: Estado) -> Estado:
        """Encerra quando o orçamento não cobre nem a compra de nenhum candidato."""
        candidatos = estado.get("candidatos") or []
        orcamento = estado.get("orcamento") or 0.0
        mais_acessivel = min(candidatos, key=lambda c: self._numero(c, "preco_entrada_medio"))
        entrada = self._numero(mais_acessivel, "preco_entrada_medio")
        build = self._numero(mais_acessivel, "custo_build_estimado")
        mensagem = (
            f"O orçamento de {self._formatar_moeda(orcamento)} não cobre nem a compra dos clássicos "
            f"compatíveis com o estilo {estado.get('estilo', 'GERAL')}. A opção mais acessível é o "
            f"{mais_acessivel.get('modelo', '?')} ({mais_acessivel.get('montadora', '')}), com entrada "
            f"por volta de {self._formatar_moeda(entrada)}. Somando o build estimado de "
            f"{self._formatar_moeda(build)}, o projeto pede cerca de "
            f"{self._formatar_moeda(entrada + build)} — faltam "
            f"{self._formatar_moeda(max(0.0, entrada + build - orcamento))} frente ao que você tem. "
            "Aumente o orçamento ou reveja o escopo do projeto."
        )
        self.logger.info("Orçamento insuficiente para qualquer candidato: encerrando.")
        estado["ranking"] = []
        estado["nota_viabilidade"] = 0.0
        estado["recomendacao"] = mensagem
        estado["resposta"] = mensagem
        return estado

    def _no_refinar_busca(self, estado: Estado) -> Estado:
        """Refaz a busca na base vetorial com o foco no risco do candidato líder."""
        estado["tentativas_recuperacao"] = estado.get("tentativas_recuperacao", 0) + 1
        if self._recuperacao is None:
            return estado
        lider = self._candidato_lider(estado) or {}
        consulta = " ".join(
            parte
            for parte in (
                str(lider.get("modelo", "")),
                str(lider.get("montadora", "")),
                estado.get("estilo", ""),
                "ferrugem estrutural longarina peças crônicos preparação",
            )
            if parte
        )
        trechos = self._recuperacao.recuperar(consulta, k=self.config.rag_k * 2)
        acumular_conhecimento(estado, trechos)
        self.logger.info(
            "Busca dirigida ao líder (%s) recuperou %d trecho(s).",
            lider.get("modelo", "?"),
            len(trechos),
        )
        return estado

    # ------------------------------------------------------------------
    # Arestas condicionais (as decisões do grafo)
    # ------------------------------------------------------------------
    @staticmethod
    def _apos_acesso(estado: Estado) -> str:
        return "encerrar" if estado.get("erro") else "briefing"

    @staticmethod
    def _apos_catalogo(estado: Estado) -> str:
        return "especialistas" if estado.get("candidatos") else "sem_candidatos"

    @staticmethod
    def _apos_mercado(estado: Estado) -> str:
        """Pára cedo quando nem a entrada de qualquer candidato cabe no orçamento."""
        notas = [(item.get("mercado") or {}).get("nota") for item in estado.get("avaliacoes") or []]
        if notas and all(nota == 0 for nota in notas):
            return "aviso_orcamento"
        return "continuar"

    def _apos_cronicos(self, estado: Estado) -> str:
        """Decide entre buscar mais contexto sobre o risco do líder ou fechar o veredito."""
        if not estado.get("recuperacao_ativa"):
            return "consultor"
        if estado.get("tentativas_recuperacao", 0) >= self.LIMITE_REFINAMENTO:
            return "consultor"
        lider = self._candidato_lider(estado)
        if lider is None:
            return "consultor"
        if self._nota_cronicos(lider) >= self.LIMIAR_RISCO_CRONICO:
            return "consultor"
        return "refinar_busca"

    # ------------------------------------------------------------------
    # Apoio
    # ------------------------------------------------------------------
    @staticmethod
    def _candidato_lider(estado: Estado) -> dict | None:
        """Candidato com melhor nota ponderada até o momento (mesmos pesos do veredito)."""
        avaliacoes = estado.get("avaliacoes") or []
        if not avaliacoes:
            return None
        return max(avaliacoes, key=Orquestrador._pontuacao_parcial)

    @staticmethod
    def _pontuacao_parcial(avaliacao: dict) -> float:
        return sum(
            float((avaliacao.get(chave) or {}).get("nota", 0.0)) * peso
            for chave, peso in PESOS.items()
        )

    @staticmethod
    def _nota_cronicos(avaliacao: dict) -> float:
        return float((avaliacao.get("cronicos") or {}).get("nota", 0.0))

    @staticmethod
    def _numero(candidato: dict, chave: str) -> float:
        try:
            return float(candidato.get(chave) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _formatar_moeda(valor: float | None) -> str:
        if not valor:
            return "R$ 0"
        return f"R$ {valor:,.0f}".replace(",", ".")

    @staticmethod
    def _avaliacao_base(candidato: dict) -> dict:
        """Cria a linha de avaliação que os agentes vão preencher."""
        return {
            "modelo": candidato.get("modelo", ""),
            "montadora": candidato.get("montadora", ""),
            "anos": candidato.get("anos", ""),
            "tracao": candidato.get("tracao", ""),
            "preco_entrada_medio": candidato.get("preco_entrada_medio"),
            "custo_build_estimado": candidato.get("custo_build_estimado"),
            "estilos_ideais": candidato.get("estilos_ideais", []),
        }

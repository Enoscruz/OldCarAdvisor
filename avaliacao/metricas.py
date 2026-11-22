"""Verificações determinísticas sobre o estado final de uma consultoria.

Cada verificação é uma expectativa isolada e nomeada. Isolar as expectativas
tem uma consequência prática: quando algo quebra, o relatório diz *o quê*
quebrou (fluxo, orçamento, invariante das notas) em vez de apenas reprovar o
caso inteiro.

As invariantes de `notas_no_intervalo` e `ranking_ordenado` valem para
qualquer caso com ranking: elas protegem os contratos do domínio (nota de 0 a
10 e veredito ordenado da melhor para a pior opção).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from avaliacao.casos import Caso

# Chaves de nota que cada agente especialista preenche na linha de avaliação.
NOTAS = ("tecnico", "mercado", "pecas", "cronicos")


@dataclass
class Verificacao:
    """Uma expectativa checada, com o motivo da falha quando aplicável."""

    nome: str
    ok: bool
    detalhe: str = ""


@dataclass
class ResultadoCaso:
    """Resultado da avaliação de um caso."""

    nome: str
    pergunta: str
    latencia_ms: int
    verificacoes: list[Verificacao] = field(default_factory=list)
    erro: str = ""
    # Notas do LLM-as-judge, quando a etapa opcional é acionada.
    juiz: dict | None = None

    @property
    def aprovado(self) -> bool:
        return not self.erro and all(verificacao.ok for verificacao in self.verificacoes)

    @property
    def aprovadas(self) -> int:
        return sum(1 for verificacao in self.verificacoes if verificacao.ok)

    @property
    def falhas(self) -> list[Verificacao]:
        return [verificacao for verificacao in self.verificacoes if not verificacao.ok]


def avaliar(caso: Caso, estado: dict, latencia_ms: int) -> ResultadoCaso:
    """Confere o estado final da consultoria contra as expectativas do caso."""
    resultado = ResultadoCaso(nome=caso.nome, pergunta=caso.pergunta, latencia_ms=latencia_ms)

    def checar(nome: str, ok: bool, detalhe: str = "") -> None:
        resultado.verificacoes.append(Verificacao(nome=nome, ok=bool(ok), detalhe=detalhe))

    # --- Erro: esperado (acesso negado) ou ausente (fluxo normal) ---
    erro = str(estado.get("erro") or "")
    if caso.exige_erro:
        checar("erro_esperado", bool(erro), f"erro={erro!r}")
    else:
        checar("sem_erro", not erro, f"erro={erro!r}")

    # --- Briefing extraído do pedido ---
    if caso.estilo_esperado is not None:
        estilo = str(estado.get("estilo") or "")
        checar("estilo", estilo == caso.estilo_esperado, f"esperado={caso.estilo_esperado} obtido={estilo}")

    if caso.orcamento_esperado is not None:
        orcamento = estado.get("orcamento")
        ok = orcamento is not None and abs(float(orcamento) - caso.orcamento_esperado) < 1.0
        checar("orcamento", ok, f"esperado={caso.orcamento_esperado:.0f} obtido={orcamento}")

    # --- Caminho percorrido no grafo de decisão ---
    fluxo = [str(no) for no in estado.get("fluxo") or []]
    faltantes = [no for no in caso.fluxo_obrigatorio if no not in fluxo]
    checar(
        "fluxo_obrigatorio",
        not faltantes,
        f"faltando={faltantes}" if faltantes else f"fluxo={' -> '.join(fluxo)}",
    )
    indevidos = [no for no in caso.fluxo_proibido if no in fluxo]
    checar("fluxo_proibido", not indevidos, f"nao deveriam rodar={indevidos}" if indevidos else "")

    if caso.fluxo_final is not None:
        ultimo = fluxo[-1] if fluxo else ""
        checar("fluxo_final", ultimo == caso.fluxo_final, f"esperado={caso.fluxo_final} obtido={ultimo}")

    # --- Ranking e invariantes do domínio ---
    ranking = list(estado.get("ranking") or [])
    if caso.exige_ranking:
        checar("ranking", bool(ranking), f"{len(ranking)} candidato(s)")

    if ranking:
        notas = [
            float((item.get(chave) or {}).get("nota", 0.0))
            for item in ranking
            for chave in NOTAS
        ]
        fora = [nota for nota in notas if not 0.0 <= nota <= 10.0]
        checar("notas_no_intervalo", not fora, f"fora de 0-10: {fora}" if fora else "todas em 0-10")

        finais = [float(item.get("nota_final", 0.0)) for item in ranking]
        checar("ranking_ordenado", finais == sorted(finais, reverse=True), f"nota_final={finais}")

    # --- Resposta entregue ao usuário ---
    resposta = str(estado.get("resposta") or "").strip()
    checar("resposta", bool(resposta), f"{len(resposta)} caractere(s)")

    # --- Fundamentação na base vetorial (RAG) ---
    if caso.exige_conhecimento:
        trechos = estado.get("conhecimento") or []
        checar("conhecimento_rag", bool(trechos), f"{len(trechos)} trecho(s)")

    # --- Modelo citado pelo usuário deve ser priorizado no shortlist ---
    if caso.primeira_escolha is not None:
        candidatos = estado.get("candidatos") or []
        primeiro = str(candidatos[0].get("modelo", "")) if candidatos else ""
        checar(
            "primeira_escolha",
            primeiro == caso.primeira_escolha,
            f"esperado={caso.primeira_escolha} obtido={primeiro}",
        )

    # --- Conteúdo mínimo da resposta (mensagens de encerramento) ---
    if caso.trecho_esperado:
        encontrado = caso.trecho_esperado.lower() in resposta.lower()
        checar("trecho_resposta", encontrado, f"procurado={caso.trecho_esperado!r}")

    return resultado


def resumir(resultados: list[ResultadoCaso]) -> dict[str, float | int | None]:
    """Agrega os resultados em métricas para o relatório e para o MLflow."""
    total = len(resultados)
    aprovados = sum(1 for resultado in resultados if resultado.aprovado)
    verificacoes = sum(len(resultado.verificacoes) for resultado in resultados)
    verificacoes_ok = sum(resultado.aprovadas for resultado in resultados)
    latencias = [resultado.latencia_ms for resultado in resultados]
    notas_juiz = [
        float(resultado.juiz["media"])
        for resultado in resultados
        if resultado.juiz
    ]

    return {
        "casos": total,
        "casos_aprovados": aprovados,
        "aprovacao_pct": round(aprovados / total * 100, 1) if total else 0.0,
        "verificacoes": verificacoes,
        "verificacoes_ok": verificacoes_ok,
        "verificacoes_pct": round(verificacoes_ok / verificacoes * 100, 1) if verificacoes else 0.0,
        "latencia_media_ms": round(sum(latencias) / total, 1) if total else 0.0,
        "latencia_max_ms": max(latencias) if latencias else 0,
        "juiz_media": round(sum(notas_juiz) / len(notas_juiz), 2) if notas_juiz else None,
    }

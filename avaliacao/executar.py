"""CLI da suíte de avaliação da consultoria.

Roda os casos de `avaliacao.casos` contra o orquestrador, imprime o relatório
por verificação e devolve código de saída diferente de zero quando a taxa de
aprovação fica abaixo do limiar. É esse código de saída que faz o CI barrar uma
regressão em vez de apenas avisar sobre ela.

Exemplos:
    py -m avaliacao.executar
    py -m avaliacao.executar --limiar 1.0 --json relatorios/avaliacao.json --mlflow
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from avaliacao.casos import CASOS, NOMES
from avaliacao.juiz import JuizLLM
from avaliacao.metricas import ResultadoCaso, avaliar, resumir
from avaliacao.rastreador import Rastreador
from app.container import construir_container
from app.servicos.config import Config
from app.servicos.gemini_service import criar_gemini_service
from app.servicos.logger_service import LoggerService
from app.servicos.prompt_service import PromptService


def executar_casos(
    container,
    logger,
    apenas: list[str] | None = None,
    juiz: JuizLLM | None = None,
) -> list[ResultadoCaso]:
    """Executa a consultoria para cada caso e avalia o estado resultante."""
    selecionados = [caso for caso in CASOS if not apenas or caso.nome in apenas]
    resultados: list[ResultadoCaso] = []

    for caso in selecionados:
        inicio = perf_counter()
        try:
            estado = container.orquestrador.executar(caso.pergunta, caso.email)
        except Exception as exc:
            logger.exception("Caso '%s' falhou durante a execução: %s", caso.nome, exc)
            resultados.append(
                ResultadoCaso(nome=caso.nome, pergunta=caso.pergunta, latencia_ms=0, erro=str(exc))
            )
            continue

        resultado = avaliar(caso, estado, int((perf_counter() - inicio) * 1000))
        if juiz is not None:
            resultado.juiz = juiz.avaliar(caso.pergunta, estado)
        resultados.append(resultado)

    return resultados


def imprimir_relatorio(resultados: list[ResultadoCaso], resumo: dict) -> None:
    """Imprime o relatório legível: um bloco por caso, com as falhas detalhadas."""
    print("=" * 78)
    print(f"AVALIAÇÃO DA CONSULTORIA — {resumo['casos']} caso(s)")
    print("=" * 78)

    for resultado in resultados:
        marca = "OK   " if resultado.aprovado else "FALHA"
        print(
            f"[{marca}] {resultado.nome:<32} "
            f"{resultado.aprovadas}/{len(resultado.verificacoes)} verificações · "
            f"{resultado.latencia_ms} ms"
        )
        if resultado.erro:
            print(f"         execução interrompida: {resultado.erro}")
        for falha in resultado.falhas:
            detalhe = f" ({falha.detalhe})" if falha.detalhe else ""
            print(f"         - {falha.nome}{detalhe}")
        if resultado.juiz:
            notas = ", ".join(f"{k} {v}" for k, v in resultado.juiz["notas"].items())
            print(f"         juiz LLM: média {resultado.juiz['media']} ({notas})")

    print("-" * 78)
    resumo_juiz = (
        f" · juiz LLM média {resumo['juiz_media']}" if resumo.get("juiz_media") is not None else ""
    )
    print(
        f"Resumo: {resumo['casos_aprovados']}/{resumo['casos']} casos aprovados "
        f"({resumo['aprovacao_pct']}%) · "
        f"{resumo['verificacoes_ok']}/{resumo['verificacoes']} verificações "
        f"({resumo['verificacoes_pct']}%) · "
        f"latência média {resumo['latencia_media_ms']} ms{resumo_juiz}"
    )


def montar_relatorio(
    config: Config,
    resultados: list[ResultadoCaso],
    resumo: dict,
) -> dict:
    """Monta o relatório completo (ambiente + resumo + detalhe por caso)."""
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ambiente": {
            "gemini_modo": config.gemini_modo,
            "embedding_modo": config.embedding_modo,
            "rag_ativo": config.rag_ativo,
            "rag_k": config.rag_k,
            "integracoes_online": config.integracoes_online,
        },
        "resumo": resumo,
        "casos": [
            {
                "nome": resultado.nome,
                "pergunta": resultado.pergunta,
                "aprovado": resultado.aprovado,
                "latencia_ms": resultado.latencia_ms,
                "erro": resultado.erro,
                "juiz": resultado.juiz,
                "verificacoes": [
                    {"nome": verificacao.nome, "ok": verificacao.ok, "detalhe": verificacao.detalhe}
                    for verificacao in resultado.verificacoes
                ],
            }
            for resultado in resultados
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m avaliacao.executar",
        description="Avalia a consultoria multi-agente com casos e expectativas verificáveis.",
    )
    parser.add_argument(
        "--caso", action="append", dest="casos", metavar="NOME",
        help=f"Roda apenas estes casos (repetível). Disponíveis: {', '.join(NOMES)}.",
    )
    parser.add_argument(
        "--limiar", type=float, default=1.0,
        help="Taxa mínima de casos aprovados, de 0 a 1 (padrão: 1.0).",
    )
    parser.add_argument(
        "--json", dest="destino_json", default="",
        help="Caminho do relatório JSON gravado ao final.",
    )
    rastreamento = parser.add_mutually_exclusive_group()
    rastreamento.add_argument(
        "--mlflow", dest="usar_mlflow", action="store_true",
        help="Registra a execução no MLflow (padrão).",
    )
    rastreamento.add_argument(
        "--sem-mlflow", dest="usar_mlflow", action="store_false",
        help="Não registra a execução no MLflow.",
    )
    parser.set_defaults(usar_mlflow=True)
    parser.add_argument(
        "--juiz", action="store_true",
        help="Aciona o LLM-as-judge (requer GEMINI_MODO=vertex com credenciais).",
    )
    args = parser.parse_args(argv)

    container = construir_container()
    config = container.config
    logger = LoggerService(config).obter("avaliacao")

    juiz = None
    if args.juiz:
        juiz = JuizLLM(
            config,
            logger,
            PromptService(config, logger),
            criar_gemini_service(config, logger),
        )
        if not juiz.disponivel:
            logger.warning(
                "Etapa --juiz ignorada: GEMINI_MODO=%s não usa um modelo real para julgar.",
                config.gemini_modo,
            )
            juiz = None

    resultados = executar_casos(container, logger, args.casos, juiz)
    if args.casos and not resultados:
        print(
            f"Nenhum caso corresponde a {', '.join(args.casos)}. Disponíveis: {', '.join(NOMES)}.",
            file=sys.stderr,
        )
        return 2

    resumo = resumir(resultados)
    imprimir_relatorio(resultados, resumo)

    relatorio = montar_relatorio(config, resultados, resumo)
    if args.destino_json:
        destino = Path(args.destino_json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Relatório gravado em {destino}")

    if args.usar_mlflow:
        rastreador = Rastreador(
            logger,
            experimento="oldcaradvisor-consultoria",
            # Backend SQLite: o file store do MLflow 3.x está descontinuado.
            uri_tracking=f"sqlite:///{(config.pasta_logs / 'mlflow.db').as_posix()}",
        )
        rastreador.registrar(
            parametros={
                "gemini_modo": config.gemini_modo,
                "embedding_modo": config.embedding_modo,
                "rag_ativo": config.rag_ativo,
                "rag_k": config.rag_k,
                "integracoes_online": config.integracoes_online,
                "limiar": args.limiar,
                "juiz_acionado": bool(juiz),
            },
            metricas={
                chave: float(valor)
                for chave, valor in resumo.items()
                if isinstance(valor, (int, float)) and not isinstance(valor, bool)
            },
            artefatos=[args.destino_json] if args.destino_json else (),
            nome_execucao=f"avaliacao-{config.gemini_modo}",
            tags={"origem": "suíte de avaliação", "modo": config.gemini_modo},
        )

    aprovacao = float(resumo["aprovacao_pct"]) / 100
    if aprovacao < args.limiar:
        print(
            f"REPROVADO: aprovação {aprovacao:.0%} abaixo do limiar {args.limiar:.0%}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

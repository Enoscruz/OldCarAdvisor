"""CLI da consultoria multi-agente de clássicos.

Exemplo:
    py main.py -p "Tenho R$ 90 mil para um Opala hot rod no Sudeste." -e admin@oldcaradvisor.com
"""

from __future__ import annotations

import argparse
import sys

from app.container import construir_container


def _formatar_moeda(valor: float | None) -> str:
    if not valor:
        return "não informado"
    return f"R$ {valor:,.0f}".replace(",", ".")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OldCarAdvisor — recomenda clássicos para customização a partir de orçamento e estilo."
    )
    parser.add_argument("-p", "--pergunta", required=True, help="Pedido do usuário (orçamento + estilo + região).")
    parser.add_argument("-e", "--email", default="admin@oldcaradvisor.com", help="E-mail do usuário (validado pela política de acesso).")
    args = parser.parse_args()

    container = construir_container()
    estado = container.orquestrador.executar(args.pergunta, args.email)

    if estado.get("erro"):
        print(f"Erro: {estado['erro']}", file=sys.stderr)
        return 1

    print("=" * 72)
    print(
        "Briefing: "
        f"estilo={estado.get('estilo', 'GERAL')} | "
        f"orçamento={_formatar_moeda(estado.get('orcamento'))} | "
        f"região={estado.get('regiao') or 'não informada'}"
    )
    print("=" * 72)
    print(estado.get("resposta", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

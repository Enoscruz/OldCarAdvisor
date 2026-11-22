# OldCarAdvisor

Consultoria multi-agente de carros clássicos para projetos de customização. A
partir de um pedido em linguagem natural (orçamento + estilo + região), o
sistema monta um shortlist de clássicos compatíveis e o avalia sob quatro
frentes — engenharia, mercado, disponibilidade de peças e problemas crônicos —
antes de fechar uma recomendação fundamentada.

A consultoria é um **grafo de decisão** (`LangGraph`), não uma sequência fixa de
chamadas: o fluxo encerra cedo quando não há candidatos viáveis e pode refazer a
busca na base vetorial quando o candidato líder tem risco crônico relevante. O
caminho percorrido fica auditável em `estado["fluxo"]`.

## Arquitetura

```
START → acesso ─(negado)→ END
              └(autorizado)→ briefing → catálogo
catálogo ─(sem candidatos)→ sem_candidatos → END
         └(com candidatos)→ engenheiro → mercado
mercado ─(não fecha entrada)→ aviso_orçamento → END
        └(algo cabe)→ aftermarket → crônicos
crônicos ─(risco crônico + tentativa)→ refinar_busca
         └(risco aceitável)→ consultor → END
refinar_busca → consultor → END
```

- **Agentes especialistas** (`app/agentes`): engenharia, mercado, aftermarket,
  crônicos e o consultor que consolida o veredito.
- **RAG** (`app/orquestrador/grafo_rag.py` + `app/servicos`): recuperação vetorial
  (`LangChain` + `Chroma`) sobre o catálogo e a base de conhecimento em Markdown,
  fundamentando cada parecer.
- **Controle de acesso** (`rls.xlsx`): níveis `GOD` / `A` / `B` validados por
  e-mail antes de qualquer consulta.
- **Governança**: cada interação é auditada (SQLite em dev, Azure SQL em
  produção).

## Stack

- Python 3.12 · LangGraph · LangChain · Chroma · Streamlit · pandas
- Gemini / Vertex AI (com **modo mock offline** para rodar sem credenciais)
- Azure (App Service for Containers, ACR, Key Vault, Azure SQL, Entra ID Easy
  Auth) provisionado por **Bicep** e publicado por **GitHub Actions**
- Avaliação determinística + MLflow (`avaliacao/`)

## Estrutura

```
app/               código da aplicação (agentes, serviços, orquestrador, prompts)
avaliacao/         suíte de avaliação da consultoria (casos, métricas, MLflow)
dados/             catálogo, base de conhecimento e política de acesso
infra/             templates Bicep (Fase 1 de deploy no Azure)
scripts/           geradores de dados de exemplo
sql/               schema de governança (Azure SQL)
main.py            CLI
streamlit_app.py   interface web
DEPLOY.md          passo a passo de deploy no Azure
```

## Como executar (local, sem nuvem)

```bash
py -m pip install -r requirements.txt
copy .env.example .env          # GEMINI_MODO=mock já roda offline
py scripts/gerar_dados_exemplo.py   # (opcional) regera os arquivos de exemplo

# CLI
py main.py -p "Tenho R$ 90 mil para um Opala hot rod no Sudeste."

# Interface web
py -m streamlit run streamlit_app.py
```

Emails de exemplo em `dados/rls.xlsx`: `admin@oldcaradvisor.com` (GOD) ·
`analista@oldcaradvisor.com` (A) · `usuario@oldcaradvisor.com` (B).

## Avaliação e MLOps

```bash
py -m pip install -r requirements-avaliacao.txt
py -m avaliacao.executar --limiar 1.0 --json relatorios/avaliacao.json
```

A suíte roda casos reais contra o orquestrador em modo offline e falha quando a
taxa de aprovação cai abaixo do limiar — o mesmo gate usado no CI.

## Deploy

O deploy no Azure (App Service for Containers + ACR + Key Vault + Entra ID +
Azure SQL) está documentado passo a passo em [`DEPLOY.md`](DEPLOY.md).

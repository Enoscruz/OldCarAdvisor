# Deploy do OldCarAdvisor no Azure — passo a passo

Importante: eu não tenho acesso à sua assinatura Azure (meu ambiente não
alcança `management.azure.com` nem `login.microsoftonline.com`), então não
consigo rodar esses comandos por você. O que preparei é o pacote completo
— Dockerfile, IaC (Bicep), pipeline de CI/CD e as mudanças de código — para
que você (ou quem tiver acesso ao `az login`) rode esta sequência exata e
chegue num deploy funcionando. Cada passo tem o comando pronto.

Escopo: Fase 1 do plano (App Service for Containers + ACR + Key Vault +
Entra ID + Azure SQL, incluindo a auditoria/governança). Azure AI Search e
Blob Storage ficam para a Fase 2.

## 0. Pré-requisitos

- Azure CLI instalado (`az --version`) e logado: `az login`
- Docker instalado (para testar a imagem localmente antes do deploy)
- Permissão para criar recursos e fazer *role assignments* na subscription
- Permissão no Entra ID para registrar uma aplicação (ou alguém do time de TI que possa fazer isso)

## 1. Testar o container localmente (opcional, mas recomendado)

```bash
cd "OldCarAdvisor"
cp .env.example .env   # preencha com valores reais de teste
docker build -t oldcaradvisor-local .
docker run --rm -p 8501:8501 --env-file .env oldcaradvisor-local
```

Abra `http://localhost:8501` e confirme que o login manual (rls.xlsx) ainda
funciona — é o fallback para quando não há Easy Auth.

## 2. Criar o grupo de recursos

```bash
az group create --name rg-oldcaradvisor-prod --location brazilsouth
```

## 3. Registrar o app no Microsoft Entra ID (para o Easy Auth)

```bash
az ad app create --display-name "OldCarAdvisor" \
  --sign-in-audience AzureADMyOrg
```

Anote o `appId` retornado (é o `entraClientId`). Pegue o `tenantId` com:

```bash
az account show --query tenantId -o tsv
```

Crie um client secret:

```bash
az ad app credential reset --id <appId> --display-name "easyauth" --years 1
```

Anote o `password` retornado (é o `entraClientSecret` — só aparece uma vez).

Depois do deploy (passo 5), volte aqui e adicione a URL de redirect:
`https://<nome-do-app>.azurewebsites.net/.auth/login/aad/callback` em
**Redirect URIs** do app registration (portal ou `az ad app update`).

## 4. Validar o Bicep

```bash
cd infra
az bicep build --file main.bicep
```

Corrija qualquer erro apontado antes de prosseguir — este template ainda não
foi testado contra uma assinatura Azure real.

## 5. Deploy da infraestrutura

Copie `main.parameters.example.json` para `main.parameters.json` e preencha
os valores **não sensíveis**. Senha do SQL e client secret do Entra vão só
na linha de comando (não fiquem em arquivo versionado):

```bash
az deployment group create \
  --resource-group rg-oldcaradvisor-prod \
  --template-file main.bicep \
  --parameters main.parameters.json \
  --parameters azureSqlSenha='<senha-do-azure-sql>' \
  --parameters entraClientSecret='<secret-gerado-no-passo-3>'
```

Guarde os outputs (`appServiceName`, `appServiceUrl`, `acrLoginServer`,
`keyVaultName`) — você vai usar nos próximos passos.

## 6. Criar a tabela de governança no Azure SQL

Rode o script uma vez, com qualquer cliente SQL (Azure Data Studio, `sqlcmd`,
ou o próprio portal):

```bash
sqlcmd -S <azureSqlServer> -d <azureSqlDatabase> -U <azureSqlUsuario> -P '<senha>' -i ../sql/governanca_schema.sql
```

## 7. Build e push da primeira imagem real

O Bicep sobe o App Service com uma imagem placeholder. Substitua pela
imagem de verdade:

```bash
cd ..   # volta pra raiz do projeto
az acr build --registry <acrLoginServer sem .azurecr.io> --image oldcaradvisor:latest .
az webapp config container set \
  --name <appServiceName> \
  --resource-group rg-oldcaradvisor-prod \
  --container-image-name <acrLoginServer>/oldcaradvisor:latest
az webapp restart --name <appServiceName> --resource-group rg-oldcaradvisor-prod
```

## 8. Configurar o CI/CD (GitHub Actions)

Crie uma identidade federada (sem secret de longa duração) para o GitHub
Actions logar no Azure:

```bash
az ad app create --display-name "github-oldcaradvisor-deploy"
# anote o appId (AZURE_CLIENT_ID)
az ad app federated-credential create --id <appId> --parameters '{
  "name": "github-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<org>/<repo>:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
az role assignment create --assignee <appId> --role Contributor \
  --scope /subscriptions/<subscriptionId>/resourceGroups/rg-oldcaradvisor-prod
```

No repositório GitHub, em **Settings → Secrets and variables → Actions**,
crie:

| Secret | Valor |
|---|---|
| `AZURE_CLIENT_ID` | appId acima |
| `AZURE_TENANT_ID` | tenantId |
| `AZURE_SUBSCRIPTION_ID` | sua subscription |
| `ACR_NAME` | nome do ACR (sem `.azurecr.io`) |
| `WEBAPP_NAME` | `appServiceName` do passo 5 |
| `RESOURCE_GROUP` | `rg-oldcaradvisor-prod` |

A partir daí, todo push em `main` builda a imagem e faz o deploy sozinho
(`.github/workflows/deploy.yml`).

## 9. Validar

- Abra `appServiceUrl` — deve redirecionar pro login do Entra ID (Easy Auth) automaticamente.
- Faça login com um e-mail que **esteja em `dados/rls.xlsx`** — outros e-mails corporativos válidos no Entra, mas fora da planilha, verão a tela de "acesso não autorizado" (é esperado: Easy Auth cuida de *quem* você é, `rls.xlsx` continua cuidando do *nível de acesso*).
- Faça uma pergunta de teste e confira em Application Insights (`Live Metrics` / `Logs`) se a chamada apareceu.
- Confira no Azure SQL (`SELECT * FROM dbo.governanca_interacoes`) se a interação foi auditada.

## O que fica para depois (Fase 2, não incluído neste pacote)

- Migrar `dados/rls.xlsx` para grupos do Entra ID ou uma tabela de autorização no Azure SQL.
- Trocar o Chroma local (`dados/vetores`, reconstruído a cada cold start) por Azure AI Search.
- Mover `dados/*.xlsx` para Azure Blob Storage.
- Restringir rede/RBAC do Azure SQL e do Storage.

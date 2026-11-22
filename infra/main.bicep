// Infraestrutura de produção do OldCarAdvisor (Fase 1 do plano de deploy).
// Escopo: resource group (crie o grupo antes com `az group create`, ver DEPLOY.md).
//
// Cobre: App Service Plan (Linux) + App Service for Containers, Azure Container
// Registry, Key Vault, Log Analytics + Application Insights, Managed Identity,
// e Easy Auth (App Service Authentication) com Microsoft Entra ID.
// NÃO cria o Azure SQL (o projeto já aponta para um Azure SQL existente) nem
// o Azure AI Search (fica para a Fase 2, junto da migração do Chroma).
//
// IMPORTANTE: valide com `az bicep build --file infra/main.bicep` antes do
// primeiro deploy — este template não foi executado contra uma assinatura
// Azure real neste momento.

@description('Prefixo curto usado nos nomes dos recursos, ex: "oldcar".')
@minLength(3)
@maxLength(10)
param namePrefix string = 'oldcar'

@description('Região dos recursos.')
param location string = resourceGroup().location

@description('SKU do App Service Plan (Linux).')
param appServicePlanSku string = 'B1'

@description('Imagem inicial usada no App Service antes do primeiro push via CI/CD (placeholder).')
param containerImagePlaceholder string = 'mcr.microsoft.com/appsvc/staticsite:latest'

@description('Servidor Azure SQL já existente, ex: meuservidor.database.windows.net.')
param azureSqlServer string

@description('Nome do banco Azure SQL já existente.')
param azureSqlDatabase string

@description('Usuário SQL usado pela aplicação (login, não a senha).')
param azureSqlUsuario string

@description('Senha do usuário SQL — passada apenas no momento do deploy e gravada no Key Vault.')
@secure()
param azureSqlSenha string

@description('Tenant ID do Microsoft Entra ID usado para o Easy Auth.')
param entraTenantId string

@description('Client ID (Application ID) do app registrado no Entra ID — ver passo 5 do DEPLOY.md.')
param entraClientId string

@description('Client secret do app registrado no Entra ID — passado apenas no deploy e gravado no Key Vault.')
@secure()
param entraClientSecret string

@description('Projeto GCP usado pelo Vertex AI (deixe vazio para manter modo mock).')
param googleCloudProject string = ''

@description('Região do Vertex AI.')
param googleCloudLocation string = 'us-central1'

var uniqueSuffix = uniqueString(resourceGroup().id)
var acrName = toLower('${namePrefix}acr${uniqueSuffix}')
var keyVaultName = take(toLower('${namePrefix}-kv-${uniqueSuffix}'), 24)
var appName = toLower('${namePrefix}-app-${uniqueSuffix}')
var planName = '${namePrefix}-plan'
var lawName = '${namePrefix}-law'
var aiName = '${namePrefix}-ai'

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource kvSecretSqlSenha 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'AZURE-SQL-SENHA'
  properties: { value: azureSqlSenha }
}

resource kvSecretEntraSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ENTRA-CLIENT-SECRET'
  properties: { value: entraClientSecret }
}

resource plan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: planName
  location: location
  kind: 'linux'
  sku: { name: appServicePlanSku }
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2023-01-01' = {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    clientAffinityEnabled: true // obrigatório: Streamlit mantém sessão em memória por instância
    siteConfig: {
      linuxFxVersion: 'DOCKER|${acr.properties.loginServer}/${containerImagePlaceholder}'
      acrUseManagedIdentityCreds: true
      healthCheckPath: '/_stcore/health'
      alwaysOn: true
      appSettings: [
        { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
        { name: 'WEBSITES_PORT', value: '8501' }
        { name: 'FONTE_DADOS', value: 'azure' }
        { name: 'GOVERNANCA_BACKEND', value: 'azure_sql' }
        { name: 'AZURE_SQL_SERVER', value: azureSqlServer }
        { name: 'AZURE_SQL_DATABASE', value: azureSqlDatabase }
        { name: 'AZURE_SQL_USUARIO', value: azureSqlUsuario }
        { name: 'AZURE_SQL_SENHA', value: '@Microsoft.KeyVault(VaultName=${keyVaultName};SecretName=AZURE-SQL-SENHA)' }
        { name: 'GOOGLE_CLOUD_PROJECT', value: googleCloudProject }
        { name: 'GOOGLE_CLOUD_LOCATION', value: googleCloudLocation }
        { name: 'GEMINI_MODO', value: empty(googleCloudProject) ? 'mock' : 'vertex' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET', value: '@Microsoft.KeyVault(VaultName=${keyVaultName};SecretName=ENTRA-CLIENT-SECRET)' }
      ]
    }
  }
}

resource authSettings 'Microsoft.Web/sites/config@2023-01-01' = {
  parent: webApp
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://login.microsoftonline.com/${entraTenantId}/v2.0'
          clientId: entraClientId
          clientSecretSettingName: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
        }
        login: {
          disableWWWAuthenticate: false
        }
      }
    }
  }
}

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var kvSecretsUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, webApp.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, webApp.id, 'KeyVaultSecretsUser')
  scope: kv
  properties: {
    roleDefinitionId: kvSecretsUserRoleId
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output appServiceName string = webApp.name
output appServiceUrl string = 'https://${webApp.properties.defaultHostName}'
output acrLoginServer string = acr.properties.loginServer
output keyVaultName string = kv.name
output appInsightsConnectionString string = appInsights.properties.ConnectionString

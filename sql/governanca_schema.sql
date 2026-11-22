-- Schema da tabela de governança/auditoria no Azure SQL.
-- Rodar uma vez (manualmente ou via step de migração no pipeline) antes de
-- colocar GOVERNANCA_BACKEND=azure_sql em produção.
-- Equivalente à tabela "interacoes" do SQLite usado em dev/local.

IF OBJECT_ID('dbo.governanca_interacoes', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.governanca_interacoes (
        id                   INT IDENTITY(1,1) PRIMARY KEY,
        criado_em            VARCHAR(32)   NOT NULL,   -- ISO 8601 UTC, mesmo formato do SQLite
        email                NVARCHAR(256) NOT NULL,
        pergunta             NVARCHAR(MAX) NOT NULL,
        pergunta_hash        CHAR(64)      NOT NULL,
        nivel                NVARCHAR(32),
        intencao             NVARCHAR(64),
        agente               NVARCHAR(64),
        fonte_dados          NVARCHAR(32),
        modelo               NVARCHAR(64),
        modo_modelo          NVARCHAR(32),
        status               NVARCHAR(16)  NOT NULL,
        erro                 NVARCHAR(1000) NULL,
        latencia_ms          INT           NOT NULL,
        tokens_entrada       INT           NOT NULL,
        tokens_saida         INT           NOT NULL,
        tokens_total         INT           NOT NULL,
        tipo_tokens          NVARCHAR(16)  NOT NULL,
        contexto_disponivel  BIT           NOT NULL,
        linhas_retornadas    INT           NOT NULL,
        feedback             INT           NULL
    );

    CREATE INDEX idx_governanca_interacoes_data  ON dbo.governanca_interacoes(criado_em);
    CREATE INDEX idx_governanca_interacoes_email ON dbo.governanca_interacoes(email);
END
GO

-- Se preferir outro nome/schema de tabela, ajuste AZURE_SQL_GOVERNANCA_TABELA
-- no .env / App Settings para bater com o nome usado aqui.

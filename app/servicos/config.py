"""Singleton de configuração carregada via variáveis de ambiente."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


class Config:
    """Gerencia caminhos do projeto e parâmetros do Gemini/Vertex AI."""

    _instancia: Config | None = None

    def __new__(cls) -> Config:
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            cls._instancia._inicializado = False
        return cls._instancia

    def __init__(self) -> None:
        if self._inicializado:
            return

        raiz = Path(__file__).resolve().parents[2]
        load_dotenv(raiz / ".env")

        self.raiz_projeto: Path = raiz
        self.pasta_dados: Path = raiz / os.getenv("PASTA_DADOS", "dados")
        self.pasta_logs: Path = raiz / os.getenv("PASTA_LOGS", "logs")
        self.pasta_prompts: Path = raiz / os.getenv("PASTA_PROMPTS", "app/prompts")
        self.pasta_conhecimento: Path = raiz / os.getenv("PASTA_CONHECIMENTO", "dados/conhecimento")
        self.pasta_vetores: Path = raiz / os.getenv("PASTA_VETORES", "dados/vetores")

        self.google_cloud_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        self.google_cloud_location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-001")
        self.nivel_log: str = os.getenv("NIVEL_LOG", "INFO")

        modo_bruto = os.getenv("GEMINI_MODO", "").strip().lower()
        if modo_bruto in ("mock", "vertex"):
            self.gemini_modo: str = modo_bruto
        elif not self.google_cloud_project:
            self.gemini_modo = "mock"
        else:
            self.gemini_modo = "vertex"

        self.azure_sql_server: str = os.getenv("AZURE_SQL_SERVER", "").strip()
        self.azure_sql_database: str = os.getenv("AZURE_SQL_DATABASE", "").strip()
        self.azure_sql_usuario: str = os.getenv("AZURE_SQL_USUARIO", "").strip()
        self.azure_sql_senha: str = os.getenv("AZURE_SQL_SENHA", "")
        self.azure_sql_driver: str = os.getenv(
            "AZURE_SQL_DRIVER",
            "ODBC Driver 18 for SQL Server",
        )
        self.azure_sql_schema: str = os.getenv("AZURE_SQL_SCHEMA", "dbo").strip() or "dbo"
        tabelas_env = os.getenv("AZURE_SQL_TABELAS", os.getenv("AZURE_SQL_TABELA", "base_final"))
        self.azure_sql_tabelas: list[str] = [
            t.strip() for t in tabelas_env.split(",") if t.strip()
        ]

        fonte_bruta = os.getenv("FONTE_DADOS", "").strip().lower()
        if fonte_bruta in ("azure", "duckdb"):
            self.fonte_dados: str = fonte_bruta
        elif self.azure_sql_server and self.azure_sql_database:
            self.fonte_dados = "azure"
        else:
            self.fonte_dados = "duckdb"

        # Backend de auditoria/governança: "sqlite" (padrão, uso local/dev)
        # ou "azure_sql" (produção — reaproveita as credenciais AZURE_SQL_*
        # acima, mas grava na tabela definida por AZURE_SQL_GOVERNANCA_TABELA).
        backend_bruto = os.getenv("GOVERNANCA_BACKEND", "").strip().lower()
        self.governanca_backend: str = backend_bruto if backend_bruto in ("sqlite", "azure_sql") else "sqlite"
        self.azure_sql_governanca_tabela: str = os.getenv(
            "AZURE_SQL_GOVERNANCA_TABELA", "dbo.governanca_interacoes"
        ).strip()

        self.chunk_tamanho: int = int(os.getenv("CHUNK_TAMANHO", "800"))
        self.chunk_sobreposicao: int = int(os.getenv("CHUNK_SOBREPOSICAO", "120"))
        self.rag_k: int = int(os.getenv("RAG_K", "5"))
        # RAG é um reforço: pode ser desligado para reduzir dependências em
        # ambientes onde Chroma/LangChain não estão instalados.
        self.rag_ativo: bool = os.getenv("RAG_ATIVO", "true").strip().lower() not in (
            "0", "false", "nao", "não", "off",
        )
        embedding_bruto = os.getenv("EMBEDDING_MODO", "").strip().lower()
        if embedding_bruto in ("local", "vertex", "fake"):
            self.embedding_modo: str = embedding_bruto
        elif self.gemini_modo == "vertex":
            self.embedding_modo = "vertex"
        else:
            self.embedding_modo = "local"

        # --- Integrações externas do domínio automotivo ---
        # Catálogo local de clássicos (arquivo em PASTA_DADOS, sem extensão).
        self.catalogo_veiculos: str = os.getenv("CATALOGO_VEICULOS", "catalogo_carros")
        # Quando False, nenhum serviço chama a internet (usa catálogo local).
        self.integracoes_online: bool = os.getenv("INTEGRACOES_ONLINE", "true").strip().lower() not in (
            "0", "false", "nao", "não", "off",
        )
        self.api_timeout: int = int(os.getenv("API_TIMEOUT", "20"))
        self.fipe_base_url: str = os.getenv(
            "FIPE_BASE_URL", "https://parallelum.com.br/fipe/api/v1"
        ).rstrip("/")
        self.nhtsa_base_url: str = os.getenv(
            "NHTSA_BASE_URL", "https://vpic.nhtsa.dot.gov/api"
        ).rstrip("/")
        self.carquery_base_url: str = os.getenv(
            "CARQUERY_BASE_URL", "https://www.carqueryapi.com/api/0.3"
        ).rstrip("/")
        self.busca_web_provider: str = os.getenv("BUSCA_WEB_PROVIDER", "ddgs").strip().lower()
        self.busca_web_max: int = int(os.getenv("BUSCA_WEB_MAX", "5"))
        self.max_candidatos: int = int(os.getenv("MAX_CANDIDATOS", "5"))
        # Fração do orçamento destinada à compra do carro; o restante é o build.
        self.fracao_entrada_orcamento: float = float(
            os.getenv("FRACAO_ENTRADA_ORCAMENTO", "0.6")
        )

        self.pasta_dados.mkdir(parents=True, exist_ok=True)
        self.pasta_logs.mkdir(parents=True, exist_ok=True)
        self.pasta_conhecimento.mkdir(parents=True, exist_ok=True)
        self.pasta_vetores.mkdir(parents=True, exist_ok=True)

        self._inicializado = True

    def tabela_azure_padrao(self) -> str:
        """Retorna a tabela Azure padrão com schema."""
        if not self.azure_sql_tabelas:
            return "dbo.base_final"
        primeira = self.azure_sql_tabelas[0]
        if "." in primeira:
            return primeira
        return f"{self.azure_sql_schema}.{primeira}"

    @classmethod
    def obter(cls) -> Config:
        """Retorna a instância singleton."""
        return cls()

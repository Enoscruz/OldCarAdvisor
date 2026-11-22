"""Fábrica de dependências — injeção centralizada de serviços e agentes."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agentes.aftermarket_agent import AftermarketAgent
from app.agentes.consultor_agent import ConsultorAgent
from app.agentes.cronicos_agent import CronicosAgent
from app.agentes.engenheiro_agent import EngenheiroAgent
from app.agentes.mercado_agent import MercadoAgent
from app.orquestrador.orquestrador import Orquestrador
from app.servicos.azure_sql_service import AzureSqlService
from app.servicos.briefing_service import BriefingService
from app.servicos.busca_web_service import BuscaWebService
from app.servicos.carquery_service import CarQueryService
from app.servicos.catalogo_service import CatalogoService
from app.servicos.conhecimento_service import ConhecimentoService
from app.servicos.config import Config
from app.servicos.controle_acesso import ControleAcesso
from app.servicos.data_service import DataService
from app.servicos.embedding_service import EmbeddingService
from app.servicos.fipe_service import FipeService
from app.servicos.gemini_service import criar_gemini_service
from app.servicos.governanca_service import GovernancaService
from app.servicos.logger_service import LoggerService
from app.servicos.nhtsa_service import NhtsaService
from app.servicos.prompt_service import PromptService
from app.servicos.recuperacao_service import RecuperacaoService
from app.servicos.vetor_service import VetorService


@dataclass
class ContainerOldCarAdvisor:
    """Agrupa instâncias prontas para uso pela aplicação."""

    config: Config
    data_service: DataService
    catalogo_service: CatalogoService
    orquestrador: Orquestrador
    controle_acesso: ControleAcesso
    governanca_service: GovernancaService
    buscas_web: BuscaWebService | None = None
    recuperacao_service: RecuperacaoService | None = None
    azure_sql_service: AzureSqlService | None = field(default=None)


def construir_container() -> ContainerOldCarAdvisor:
    """Monta o grafo de dependências da plataforma de clássicos."""
    config = Config.obter()
    logger_service = LoggerService(config)

    data_service = DataService(config, logger_service.obter("data"))
    prompt_service = PromptService(config, logger_service.obter("prompt"))
    gemini_service = criar_gemini_service(config, logger_service.obter("gemini"))

    controle_acesso = ControleAcesso(config, logger_service.obter("acesso"), data_service)
    governanca_service = GovernancaService(config, logger_service.obter("governanca"))

    # Integrações externas do domínio automotivo.
    briefing_service = BriefingService(config, logger_service.obter("briefing"))
    catalogo_service = CatalogoService(config, logger_service.obter("catalogo"))
    fipe_service = FipeService(config, logger_service.obter("fipe"))
    _nhtsa_service = NhtsaService(config, logger_service.obter("nhtsa"))
    _carquery_service = CarQueryService(config, logger_service.obter("carquery"))
    busca_web_service = BuscaWebService(config, logger_service.obter("busca_web"))

    # RAG: base de conhecimento vetorial (LangChain + Chroma).
    recuperacao_service = _montar_recuperacao(config, logger_service, catalogo_service)

    # Agentes especialistas.
    engenheiro_agent = EngenheiroAgent(
        config, logger_service.obter("engenheiro"), prompt_service, gemini_service, recuperacao_service
    )
    mercado_agent = MercadoAgent(
        config, logger_service.obter("mercado"), prompt_service, gemini_service, fipe_service,
        recuperacao_service,
    )
    aftermarket_agent = AftermarketAgent(
        config, logger_service.obter("aftermarket"), prompt_service, gemini_service,
        busca_web_service, recuperacao_service,
    )
    cronicos_agent = CronicosAgent(
        config, logger_service.obter("cronicos"), prompt_service, gemini_service,
        busca_web_service, recuperacao_service,
    )
    consultor_agent = ConsultorAgent(
        config, logger_service.obter("consultor"), prompt_service, gemini_service, recuperacao_service
    )

    orquestrador = Orquestrador(
        config,
        logger_service.obter("orquestrador"),
        controle_acesso,
        briefing_service,
        catalogo_service,
        engenheiro_agent,
        mercado_agent,
        aftermarket_agent,
        cronicos_agent,
        consultor_agent,
        recuperacao_service,
    )

    return ContainerOldCarAdvisor(
        config=config,
        data_service=data_service,
        catalogo_service=catalogo_service,
        orquestrador=orquestrador,
        controle_acesso=controle_acesso,
        governanca_service=governanca_service,
        buscas_web=busca_web_service,
        recuperacao_service=recuperacao_service,
        azure_sql_service=None,
    )


def _montar_recuperacao(
    config: Config,
    logger_service: LoggerService,
    catalogo_service: CatalogoService,
) -> RecuperacaoService | None:
    """Monta a base vetorial; o RAG é um reforço e não bloqueia a plataforma."""
    logger = logger_service.obter("rag")
    if not config.rag_ativo:
        logger.info("RAG desativado por configuração (RAG_ATIVO=false).")
        return None
    try:
        embedding_service = EmbeddingService(config, logger_service.obter("embedding"))
        conhecimento_service = ConhecimentoService(
            config, logger_service.obter("conhecimento"), catalogo_service
        )
        vetor_service = VetorService(
            config, logger_service.obter("vetor"), embedding_service, conhecimento_service
        )
        return RecuperacaoService(config, logger, vetor_service)
    except Exception as exc:
        logger.warning("RAG indisponível (%s). Seguindo sem base vetorial.", exc)
        return None

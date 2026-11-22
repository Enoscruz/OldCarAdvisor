"""Interface com Vertex AI / Gemini."""

from __future__ import annotations

import logging
import re

from app.servicos.base_service import BaseService
from app.servicos.config import Config


class GeminiService(BaseService):
    """Encapsula chamadas ao modelo Gemini via Vertex AI."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self._modelo = None
        self._vertex_inicializado = False

    def _inicializar_vertex(self) -> None:
        if self._vertex_inicializado:
            return

        if not self.config.google_cloud_project:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT não configurado. Defina no arquivo .env."
            )

        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(
            project=self.config.google_cloud_project,
            location=self.config.google_cloud_location,
        )
        self._modelo = GenerativeModel(self.config.gemini_model)
        self._vertex_inicializado = True
        self.logger.info(
            "Vertex AI inicializado: projeto=%s, modelo=%s",
            self.config.google_cloud_project,
            self.config.gemini_model,
        )

    def gerar(self, prompt: str, system_prompt: str = "") -> str:
        """Gera texto a partir de prompt e instrução de sistema."""
        self._inicializar_vertex()

        from vertexai.generative_models import GenerationConfig

        conteudo = prompt
        if system_prompt:
            conteudo = f"{system_prompt.strip()}\n\n---\n\n{prompt.strip()}"

        resposta = self._modelo.generate_content(
            conteudo,
            generation_config=GenerationConfig(
                temperature=0.2,
                max_output_tokens=4096,
            ),
        )

        texto = getattr(resposta, "text", "") or ""
        if not texto and resposta.candidates:
            partes = resposta.candidates[0].content.parts
            texto = "".join(getattr(p, "text", "") for p in partes)

        return texto.strip()

    def gerar_sql(self, prompt: str, system_prompt: str = "") -> str:
        """Gera SQL e extrai apenas o bloco executável."""
        texto = self.gerar(prompt, system_prompt)
        return self._extrair_sql(texto)

    @staticmethod
    def _extrair_sql(texto: str) -> str:
        match = re.search(r"```sql\s*(.*?)\s*```", texto, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

        match = re.search(r"(SELECT\s.+)", texto, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip().rstrip(";")

        return texto.strip()


def criar_gemini_service(config: Config, logger: logging.Logger):
    """Factory que escolhe implementação real ou mock conforme configuração."""
    from app.servicos.gemini_mock_service import GeminiMockService

    if config.gemini_modo == "mock":
        return GeminiMockService(config, logger)
    return GeminiService(config, logger)


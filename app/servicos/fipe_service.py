"""Cliente da Tabela FIPE (API fipeX / parallelum) para preço de mercado.

Usada pelo Agente de Mercado para ancorar o custo de entrada em valores de
referência brasileiros. Todas as chamadas são best-effort: se a rede falhar
ou o modelo não existir na base FIPE, o método devolve vazio e o agente
segue com o valor do catálogo local.
"""

from __future__ import annotations

import logging
import re
import unicodedata

import requests

from app.servicos.base_service import BaseService
from app.servicos.config import Config


class FipeService(BaseService):
    """Consulta marca, modelo, anos e preço médio na Tabela FIPE."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)

    # ------------------------------------------------------------------
    # Endpoints básicos
    # ------------------------------------------------------------------
    def marcas(self) -> list[dict]:
        return self._get(f"{self.config.fipe_base_url}/carros/marcas") or []

    def modelos(self, marca: str) -> list[dict]:
        dados = self._get(f"{self.config.fipe_base_url}/carros/marcas/{marca}/modelos")
        if isinstance(dados, dict):
            return dados.get("modelos", [])
        return dados or []

    def anos(self, marca: str, modelo: str) -> list[dict]:
        return self._get(f"{self.config.fipe_base_url}/carros/marcas/{marca}/modelos/{modelo}/anos") or []

    def preco(self, marca: str, modelo: str, ano: str) -> dict:
        """Retorna {'valor_numerico': float, 'valor_texto': str, 'modelo': str, 'ano': str}."""
        dados = self._get(f"{self.config.fipe_base_url}/carros/marcas/{marca}/modelos/{modelo}/anos/{ano}")
        if not isinstance(dados, dict):
            return {}
        valor_texto = str(dados.get("Valor", ""))
        return {
            "valor_numerico": self._para_numero(valor_texto),
            "valor_texto": valor_texto,
            "modelo": dados.get("Modelo", ""),
            "ano": dados.get("AnoModelo", ""),
            "combustivel": dados.get("Combustivel", ""),
            "codigo_fipe": dados.get("CodigoFipe", ""),
            "mes_referencia": dados.get("MesReferencia", ""),
        }

    def buscar_preco_por_nome(self, termo: str, ano: int | None = None) -> dict:
        """Tenta localizar o modelo pelo nome textual e devolver o preço FIPE.

        Faz busca tolerante: encontra a marca cujo nome aparece no termo e o
        modelo com maior sobreposição de palavras. Retorna {} se não achar.
        """
        if not termo.strip():
            return {}

        termo_norm = self._normalizar(termo)
        marcas = self.marcas()
        marca = None
        for candidata in marcas:
            nome = self._normalizar(str(candidata.get("nome", "")))
            if nome and nome.split()[0] in termo_norm:
                marca = candidata
                break
        if not marca:
            return {}

        modelos = self.modelos(str(marca["codigo"]))
        if not modelos:
            return {}

        palavras = set(termo_norm.split())
        melhor, melhor_score = None, 0
        for modelo in modelos:
            nome = self._normalizar(str(modelo.get("nome", "")))
            score = len(palavras & set(nome.split()))
            if score > melhor_score:
                melhor, melhor_score = modelo, score
        if not melhor:
            return {}

        anos = self.anos(str(marca["codigo"]), str(melhor["codigo"]))
        if not anos:
            return {}

        escolhido = anos[0]
        if ano:
            for opcao in anos:
                if str(ano) in str(opcao.get("nome", "")):
                    escolhido = opcao
                    break

        resultado = self.preco(str(marca["codigo"]), str(melhor["codigo"]), str(escolhido["codigo"]))
        if resultado:
            resultado["marca_fipe"] = marca.get("nome", "")
            resultado["modelo_fipe"] = f"{melhor.get('nome', '')} {escolhido.get('nome', '')}".strip()
        return resultado

    # ------------------------------------------------------------------
    # Infraestrutura
    # ------------------------------------------------------------------
    def _get(self, url: str):
        if not self.config.integracoes_online:
            return None
        try:
            resposta = requests.get(url, timeout=self.config.api_timeout)
            resposta.raise_for_status()
            return resposta.json()
        except Exception as exc:
            self.logger.warning("FIPE indisponível (%s): %s", url, exc)
            return None

    @staticmethod
    def _para_numero(valor_texto: str) -> float:
        somente = re.sub(r"[^0-9,]", "", valor_texto or "")
        if not somente:
            return 0.0
        return float(somente.replace(".", "").replace(",", "."))

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", texto.lower().strip())

"""Cliente da NHTSA vPIC API (decodificação de VIN e catálogo global).

Ajuda o Agente Engenheiro a identificar a versão exata de um importado dos
anos 80/90/2000 a partir do chassi (VIN): motorização de fábrica, tração,
cilindrada e país de origem.
"""

from __future__ import annotations

import logging

import requests

from app.servicos.base_service import BaseService
from app.servicos.config import Config


class NhtsaService(BaseService):
    """Decodifica VIN e lista modelos por marca/ano via vPIC."""

    CAMPOS = (
        "Make", "Model", "ModelYear", "VehicleType", "BodyClass", "DriveType",
        "EngineCylinders", "DisplacementL", "EngineHP", "FuelTypePrimary",
        "PlantCountry", "Series", "Trim",
    )

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)

    def decodificar_vin(self, vin: str) -> dict:
        """Retorna os campos relevantes da decodificação de um VIN (17 chars)."""
        vin = (vin or "").strip()
        if len(vin) != 17:
            return {}
        url = f"{self.config.nhtsa_base_url}/vehicles/DecodeVinValues/{vin}"
        dados = self._get(url, {"format": "json"})
        resultados = (dados or {}).get("Results", [])
        if not resultados:
            return {}
        bruto = resultados[0]
        return {campo: bruto.get(campo, "") for campo in self.CAMPOS}

    def modelos_por_marca_ano(self, montadora: str, ano: int) -> list[str]:
        """Lista modelos de uma montadora para um ano (útil para importados)."""
        url = (
            f"{self.config.nhtsa_base_url}/vehicles/GetModelsForMakeYear"
            f"/make/{montadora}/modelyear/{ano}"
        )
        dados = self._get(url, {"format": "json"})
        resultados = (dados or {}).get("Results", [])
        return sorted({str(item.get("Model", "")).strip() for item in resultados if item.get("Model")})

    def _get(self, url: str, params: dict | None = None):
        if not self.config.integracoes_online:
            return None
        try:
            resposta = requests.get(url, params=params, timeout=self.config.api_timeout)
            resposta.raise_for_status()
            return resposta.json()
        except Exception as exc:
            self.logger.warning("NHTSA vPIC indisponível (%s): %s", url, exc)
            return None

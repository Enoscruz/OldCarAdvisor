"""Cliente da CarQuery API (fichas técnicas de modelos globais desde 1940).

A CarQuery responde em JSONP quando um callback é informado. Este cliente
remove o envelope do callback e devolve JSON puro, normalizando os campos
mais úteis para o Agente Engenheiro (peso, tração, motor, potência).
"""

from __future__ import annotations

import json
import logging
import re

import requests

from app.servicos.base_service import BaseService
from app.servicos.config import Config


class CarQueryService(BaseService):
    """Consulta fichas técnicas de veículos globais na CarQuery."""

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        super().__init__(config, logger)

    def ficha_tecnica(self, montadora: str, modelo: str | None = None, ano: int | None = None) -> list[dict]:
        """Retorna trims normalizados para montadora/modelo/ano informados."""
        params = {"cmd": "getTrims", "make": montadora, "format": "json"}
        if modelo:
            params["model"] = modelo
        if ano:
            params["year"] = ano

        dados = self._get(params)
        trims = (dados or {}).get("Trims", [])
        return [self._normalizar(trim) for trim in trims]

    def _normalizar(self, trim: dict) -> dict:
        return {
            "modelo": f"{trim.get('model_make_id', '')} {trim.get('model_name', '')}".strip(),
            "trim": trim.get("model_trim", ""),
            "ano": trim.get("model_year", ""),
            "carroceria": trim.get("model_body", ""),
            "motor": f"{trim.get('model_engine_type', '')} {trim.get('model_engine_cc', '')}cc".strip(),
            "cilindros": trim.get("model_engine_cyl", ""),
            "potencia_cv": self._inteiro(trim.get("model_engine_power_ps")),
            "torque_nm": self._inteiro(trim.get("model_engine_torque_nm")),
            "peso_kg": self._inteiro(trim.get("model_weight_kg")),
            "tracao": trim.get("model_drive", ""),
            "transmissao": trim.get("model_transmission_type", ""),
        }

    def _get(self, params: dict):
        if not self.config.integracoes_online:
            return None
        try:
            resposta = requests.get(
                self.config.carquery_base_url, params=params, timeout=self.config.api_timeout
            )
            resposta.raise_for_status()
            return self._jsonp_para_json(resposta.text)
        except Exception as exc:
            self.logger.warning("CarQuery indisponível (%s): %s", params, exc)
            return None

    @staticmethod
    def _jsonp_para_json(texto: str):
        # CarQuery pode devolver "( {...} )" ou "callback({...})".
        conteudo = texto.strip()
        match = re.search(r"\((\{.*\})\)\s*;?\s*$", conteudo, re.DOTALL)
        if match:
            conteudo = match.group(1)
        try:
            return json.loads(conteudo)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _inteiro(valor) -> int | None:
        if valor in (None, "", "0"):
            return None
        try:
            return int(float(valor))
        except (TypeError, ValueError):
            return None

"""Validação de acesso baseada em RLS."""

from __future__ import annotations

import logging

import pandas as pd

from app.modelos.estado import NivelAcesso
from app.servicos.base_service import BaseService
from app.servicos.config import Config
from app.servicos.data_service import DataService


class ControleAcesso(BaseService):
    """Valida usuários e níveis de acesso a partir de rls.xlsx."""

    NOME_RLS = "rls"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        data_service: DataService,
    ) -> None:
        super().__init__(config, logger)
        self._data_service = data_service

    def validar(self, email: str) -> NivelAcesso:
        """Retorna nível de acesso do usuário ou levanta PermissionError."""
        df = self._obter_rls()
        email_norm = email.strip().lower()

        col_email = self._resolver_coluna(df, ["email", "e-mail", "usuario", "user"])
        col_nivel = self._resolver_coluna(df, ["nivel", "nível", "level", "acesso"])

        if not col_email or not col_nivel:
            raise ValueError("Arquivo RLS inválido: colunas email/nivel não encontradas.")

        usuarios = df.copy()
        usuarios["_email_norm"] = usuarios[col_email].astype(str).str.strip().str.lower()
        filtro = usuarios[usuarios["_email_norm"] == email_norm]

        if filtro.empty:
            raise PermissionError(f"Acesso negado: e-mail '{email}' não autorizado.")

        nivel_bruto = str(filtro.iloc[0][col_nivel]).strip().upper()
        try:
            nivel = NivelAcesso(nivel_bruto)
        except ValueError as exc:
            raise ValueError(f"Nível de acesso inválido para '{email}': {nivel_bruto}") from exc

        self.logger.info("Acesso validado: %s -> %s", email, nivel.value)
        return nivel

    def _obter_rls(self) -> pd.DataFrame:
        try:
            return self._data_service.obter(self.NOME_RLS)
        except KeyError as exc:
            raise FileNotFoundError(
                f"Arquivo {self.NOME_RLS}.xlsx não encontrado em {self.config.pasta_dados}."
            ) from exc

    @staticmethod
    def _resolver_coluna(df: pd.DataFrame, candidatos: list[str]) -> str | None:
        colunas = {c.strip().lower(): c for c in df.columns}
        for candidato in candidatos:
            if candidato in colunas:
                return colunas[candidato]
        return None

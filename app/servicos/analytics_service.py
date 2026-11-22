"""Cálculo de métricas analíticas sobre os datasets comerciais."""

from __future__ import annotations

import logging
import re
import unicodedata

import pandas as pd

from app.servicos.azure_sql_service import AzureSqlService
from app.servicos.base_service import BaseService
from app.servicos.config import Config
from app.servicos.data_service import DataService


class AnalyticsService(BaseService):
    """Executa agregações e estatísticas descritivas em Pandas."""

    NOME_BASE = "base_final"

    def __init__(
        self,
        config: Config,
        logger: logging.Logger,
        data_service: DataService,
        azure_sql_service: AzureSqlService | None = None,
    ) -> None:
        super().__init__(config, logger)
        self._data_service = data_service
        self._azure_sql_service = azure_sql_service

    def calcular_metricas(self, pergunta: str) -> str:
        """Calcula métricas relevantes conforme palavras-chave da pergunta."""
        try:
            if self.config.fonte_dados == "azure" and self._azure_sql_service:
                tabela = self._azure_sql_service.nome_tabela_padrao()
                df = self._azure_sql_service.executar(f"SELECT TOP 5000 * FROM {tabela}")
            else:
                df = self._data_service.obter(self.NOME_BASE)
        except KeyError:
            return "Dataset base_final não disponível para análise."
        except Exception as exc:
            return f"Não foi possível ler a base analítica: {exc}"

        if df.empty:
            return "Dataset base_final está vazio."

        pergunta_norm = self._normalizar(pergunta)
        blocos: list[str] = []

        col_valor = self._resolver_coluna(df, ["tcv_full", "valor", "receita", "venda"])
        col_regiao = self._resolver_coluna(df, ["regiao", "região", "region"])
        col_cliente = self._resolver_coluna(df, ["cliente", "customer", "conta"])
        col_data = self._resolver_coluna(df, ["data_fechamento", "data", "date"])

        blocos.append(f"Total de registros: {len(df)}")

        if col_valor:
            serie = pd.to_numeric(df[col_valor], errors="coerce")
            blocos.extend(
                [
                    f"Soma de {col_valor}: {serie.sum():,.2f}",
                    f"Média de {col_valor}: {serie.mean():,.2f}",
                    f"Mínimo de {col_valor}: {serie.min():,.2f}",
                    f"Máximo de {col_valor}: {serie.max():,.2f}",
                ]
            )

        if col_regiao and col_valor and any(p in pergunta_norm for p in ("regiao", "regiao", "tendencia", "tendencia")):
            agrupado = (
                df.groupby(col_regiao)[col_valor]
                .sum()
                .sort_values(ascending=False)
            )
            blocos.append("Totais por região:")
            blocos.append(agrupado.to_string())

        if col_cliente and col_valor and any(p in pergunta_norm for p in ("cliente", "top", "ranking")):
            top = (
                df.groupby(col_cliente)[col_valor]
                .sum()
                .sort_values(ascending=False)
                .head(5)
            )
            blocos.append("Top 5 clientes por valor:")
            blocos.append(top.to_string())

        if col_data and col_valor and any(
            p in pergunta_norm for p in ("tendencia", "tendencia", "tempo", "periodo", "periodo", "mes", "mês")
        ):
            datas = pd.to_datetime(df[col_data], errors="coerce")
            df_tempo = df.assign(_periodo=datas.dt.to_period("M"))
            serie_tempo = df_tempo.groupby("_periodo")[col_valor].sum().sort_index()
            blocos.append("Evolução mensal:")
            blocos.append(serie_tempo.to_string())

        if len(blocos) == 1:
            if col_regiao and col_valor:
                agrupado = df.groupby(col_regiao)[col_valor].sum().sort_values(ascending=False)
                blocos.append("Distribuição por região:")
                blocos.append(agrupado.to_string())
            elif col_valor:
                blocos.append(f"Mediana de {col_valor}: {pd.to_numeric(df[col_valor], errors='coerce').median():,.2f}")

        self.logger.info("Analytics calculou %d bloco(s) de métricas.", len(blocos))
        return "\n".join(blocos)

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", texto.lower().strip())

    @staticmethod
    def _resolver_coluna(df: pd.DataFrame, candidatos: list[str]) -> str | None:
        mapa = {str(c).strip().lower(): c for c in df.columns}
        for candidato in candidatos:
            if candidato in mapa:
                return mapa[candidato]
        return None

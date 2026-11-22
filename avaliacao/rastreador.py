"""Registro dos experimentos de avaliação no MLflow.

O MLflow é dependência de desenvolvimento/CI (ver `requirements-avaliacao.txt`),
por isso este módulo não a assume: quando o pacote não está instalado, o
rastreador degrada para no-op e a suíte continua produzindo o relatório
normalmente. A avaliação nunca deve falhar por causa do tracking.

Com o pacote presente, o destino é `MLFLOW_TRACKING_URI` quando definido
(servidor remoto) ou o banco `logs/mlflow.db` (backend SQLite, recomendado pelo
MLflow 3.x — o backend de arquivos está descontinuado).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable


class Rastreador:
    """Envia parâmetros, métricas e relatórios de uma execução ao MLflow."""

    EXPERIMENTO_PADRAO = "oldcaradvisor-consultoria"

    def __init__(
        self,
        logger: logging.Logger,
        experimento: str | None = None,
        ativo: bool = True,
        uri_tracking: str | None = None,
    ) -> None:
        self._logger = logger
        self._experimento = experimento or self.EXPERIMENTO_PADRAO
        self._mlflow = self._importar() if ativo else None
        self._configurar_destino(uri_tracking)

    @property
    def disponivel(self) -> bool:
        return self._mlflow is not None

    @staticmethod
    def _importar() -> Any | None:
        try:
            import mlflow
        except ImportError:
            return None
        return mlflow

    def _configurar_destino(self, uri_tracking: str | None) -> None:
        """Respeita MLFLOW_TRACKING_URI e cai num diretório local em logs/."""
        if self._mlflow is None or os.getenv("MLFLOW_TRACKING_URI"):
            return
        if uri_tracking:
            self._mlflow.set_tracking_uri(uri_tracking)
            self._logger.info("MLflow apontado para %s", uri_tracking)

    def registrar(
        self,
        parametros: dict[str, Any] | None = None,
        metricas: dict[str, float] | None = None,
        artefatos: Iterable[str] = (),
        nome_execucao: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str | None:
        """Registra uma execução completa e devolve o run_id (ou None)."""
        if self._mlflow is None:
            self._logger.warning(
                "MLflow indisponível: avaliação executada sem registro de experimento."
            )
            return None

        mlflow = self._mlflow
        try:
            mlflow.set_experiment(self._experimento)
            with mlflow.start_run(run_name=nome_execucao):
                if parametros:
                    mlflow.log_params(
                        {chave: self._achatar(valor) for chave, valor in parametros.items()}
                    )
                if metricas:
                    mlflow.log_metrics({chave: float(valor) for chave, valor in metricas.items()})
                if tags:
                    mlflow.set_tags(tags)
                for artefato in artefatos:
                    caminho = Path(artefato)
                    if caminho.exists():
                        mlflow.log_artifact(str(caminho))
                run_id = mlflow.active_run().info.run_id
        except Exception as exc:
            # O tracking é observabilidade: nunca deve invalidar a avaliação.
            self._logger.warning("Falha ao registrar a execução no MLflow: %s", exc)
            return None

        self._logger.info("Execução registrada no MLflow: run_id=%s", run_id)
        return run_id

    @staticmethod
    def _achatar(valor: Any) -> str | int | float | bool:
        """O MLflow aceita apenas escalares como parâmetro."""
        if isinstance(valor, (str, int, float, bool)):
            return valor
        return str(valor)

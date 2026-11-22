# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# --- dependências de sistema ---
# unixodbc + msodbcsql18: exigidos pelo pyodbc para falar com o Azure SQL.
# curl/gnupg: necessários só durante o build para adicionar o repo da Microsoft.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg unixodbc unixodbc-dev \
    && curl -sSL -o /usr/share/keyrings/microsoft-prod.gpg https://packages.microsoft.com/keys/microsoft.asc \
    && echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- dependências Python (camada cacheável) ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- código da aplicação ---
# Observação: dados/vetores e logs/ ficam de fora da imagem de propósito.
# O índice Chroma é reconstruído no primeiro start (garantir_indice() em
# vetor_service.py); em Fase 2, isso é substituído pelo Azure AI Search.
COPY app/ ./app/
COPY dados/ ./dados/
COPY streamlit_app.py main.py ./
RUN rm -rf ./dados/vetores/* && mkdir -p ./dados/vetores ./logs

# Usuário não-root
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PYTHONUNBUFFERED=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]

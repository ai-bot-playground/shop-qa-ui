# Containerfile — shop-qa-ui (część ai-bot-playground)
# Build: podman build -t shop-qa-ui:dev -f Containerfile .
#   (działa też z `docker build`; plik jest zgodny z OCI/Dockerfile)
#
# Obraz pakuje monolit Streamlit (app.py + src/*) — patrz docker/entrypoint.sh.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git    — wymagany przez sandbox (apply_edit → git_commit) oraz uruchamianie pytest
# ca-certificates — TLS do Azure AI Foundry
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Warstwa zależności — cache'owana osobno od kodu.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Kod (uszanuj .dockerignore — bez .git, .venv itd.)
COPY . .

RUN chmod +x docker/entrypoint.sh

# Tożsamość git dla commitów wykonywanych przez sandbox wewnątrz kontenera.
RUN git config --system user.email "tool@shop-qa-ui.local" \
    && git config --system user.name "shop-qa-ui bot" \
    && git config --system --add safe.directory '*'

EXPOSE 8501

# Streamlit ma wbudowany health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health').status==200 else 1)" || exit 1

ENTRYPOINT ["docker/entrypoint.sh"]

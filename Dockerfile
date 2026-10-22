ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
# Optional CA bundle secret ("ca") is only for builds behind a TLS-intercepting proxy.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir uv==0.8.22
WORKDIR /app

# Dependencies first for layer caching (exact versions from uv.lock, no dev tools).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY data/corpus ./data/corpus

RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data/chroma /app/data/uploads \
    && chown -R appuser /app/data
USER appuser

# Download the embedding model and build the sample index at build time so the
# container starts fast and needs no network at runtime (except the optional LLM API).
RUN --mount=type=secret,id=ca,required=false,uid=10001 \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca REQUESTS_CA_BUNDLE=/run/secrets/ca; fi; \
    python scripts/ingest_corpus.py --reset

ENV PORT=8000 ENVIRONMENT=production
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health',timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 30"]

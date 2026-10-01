FROM python:3.14-slim
LABEL org.opencontainers.image.title="PenkoPerry Harness" \
      org.opencontainers.image.description="Policy-gated agents for DevOps"

# git: GitOps pull requests; bubblewrap: optional shell sandbox (PENKO_SANDBOX=bwrap)
RUN apt-get update && apt-get install -y --no-install-recommends git bubblewrap ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 penko

WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
COPY domains ./domains
COPY receipts ./receipts
COPY cli ./cli
COPY main.py ./main.py
RUN pip install --no-cache-dir ".[runtime]" && mkdir -p /app/data /workspace && chown -R penko /app/data /workspace

USER penko
ENV PENKO_API_HOST=0.0.0.0 PENKO_DATA_DIR=/app/data PENKO_DB_PATH=/app/data/memory.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# Serves the control-plane API. One-shot: docker compose run --rm penko penko run "<goal>"
CMD ["penko", "serve"]

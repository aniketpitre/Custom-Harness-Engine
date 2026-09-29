FROM python:3.12-slim

# git: GitOps pull requests; bubblewrap: optional shell sandbox (HARNESS_SANDBOX=bwrap)
RUN apt-get update && apt-get install -y --no-install-recommends git bubblewrap ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 harness

WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
COPY domains ./domains
COPY receipts ./receipts
COPY cli ./cli
COPY config ./config
COPY main.py ./main.py
RUN pip install --no-cache-dir ".[runtime]" && mkdir -p /app/data /workspace && chown -R harness /app/data /workspace

USER harness
ENV HARNESS_API_HOST=0.0.0.0 HARNESS_DATA_DIR=/app/data HARNESS_DB_PATH=/app/data/memory.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# Serves the control-plane API. One-shot CLI: docker compose run harness python -m core.gateway.cli "<goal>"
CMD ["python", "main.py"]

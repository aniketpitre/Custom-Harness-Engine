FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml ./
COPY core ./core
COPY domains ./domains
COPY receipts ./receipts
COPY main.py ./main.py
COPY config ./config

RUN pip install --no-cache-dir .

CMD ["python", "-m", "core.gateway.cli", "List the files in the current directory"]
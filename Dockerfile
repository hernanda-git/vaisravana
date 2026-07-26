# Project Vaiśravaṇa — Dockerfile (PAPER bot on Fly.io)
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY src/ src/
COPY scripts/ scripts/
COPY pyproject.toml ./

RUN pip install --no-cache-dir pydantic httpx

# Volume DB lives in /data (survives restarts); create the dir for safety.
RUN mkdir -p /data

# PAPER bot: real Binance klines → decisions → Telegram. No live orders.
CMD ["python", "scripts/bot_paper.py"]

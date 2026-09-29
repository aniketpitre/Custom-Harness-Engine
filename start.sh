#!/bin/bash
# Single-command setup: writes a private .env, then starts Vault + the harness with Docker Compose.
set -euo pipefail

echo "Harness Engine setup"
echo "--------------------"

if [ ! -f .env ]; then
    umask 077   # .env holds secrets: owner-only
    rand() { LC_ALL=C tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 40; }

    echo "Choose your LLM provider:"
    echo "1) Groq (default)  2) OpenAI  3) Anthropic  4) OpenRouter  5) NVIDIA  6) Local (Ollama/LM Studio)"
    read -r -p "Select [1-6]: " SEL
    case "$SEL" in
        2) PROVIDER=openai;     DEFAULT_MODEL="openai/gpt-4o" ;;
        3) PROVIDER=anthropic;  DEFAULT_MODEL="anthropic/claude-sonnet-4-5" ;;
        4) PROVIDER=openrouter; DEFAULT_MODEL="openrouter/auto" ;;
        5) PROVIDER=nvidia;     DEFAULT_MODEL="nvidia_nim/meta/llama-3.1-70b-instruct" ;;
        6) PROVIDER=openai;     DEFAULT_MODEL="openai/local" ;;
        *) PROVIDER=groq;       DEFAULT_MODEL="groq/openai/gpt-oss-120b" ;;
    esac
    read -r -p "Model [$DEFAULT_MODEL]: " MODEL
    MODEL=${MODEL:-$DEFAULT_MODEL}
    if [ "$SEL" = "6" ]; then
        read -r -p "Local base URL (e.g. http://host.docker.internal:11434/v1): " BASE_URL
        KEY="local-no-key"
    else
        read -r -s -p "$PROVIDER API key: " KEY; echo
    fi
    read -r -p "Telegram bot token (blank to approve via the API instead): " BOT
    CHAT=""; APPROVERS=""
    if [ -n "$BOT" ]; then
        read -r -p "Telegram approval chat id: " CHAT
        read -r -p "Telegram user id allowed to approve: " UID_
        APPROVERS="telegram:${UID_}"
    fi

    {
        echo "VAULT_DEV_ROOT_TOKEN_ID=$(rand)"
        echo "HARNESS_API_TOKEN=$(rand)"
        echo "VAULT_PROVIDER_KEY=$PROVIDER"
        echo "PROVIDER_API_KEY=$KEY"
        echo "HARNESS_MODEL=$MODEL"
        echo "TELEGRAM_BOT_TOKEN=$BOT"
        echo "TELEGRAM_APPROVAL_CHAT_ID=$CHAT"
        echo "HARNESS_APPROVERS=$APPROVERS"
        [ -n "${BASE_URL:-}" ] && echo "OPENAI_API_BASE=${BASE_URL}"
    } > .env
    chmod 600 .env
    echo ".env written (mode 600). Your API token is in .env as HARNESS_API_TOKEN."
else
    echo "Existing .env found. Continuing..."
fi

echo "Starting via Docker Compose..."
docker compose up --build -d
echo "Harness Engine API: http://127.0.0.1:8000  (Authorization: Bearer <HARNESS_API_TOKEN>)"
echo "Logs: docker compose logs -f harness"

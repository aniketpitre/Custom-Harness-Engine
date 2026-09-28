#!/bin/bash
set -e

echo "Welcome to Harness Engine Single-Command Setup!"
echo "-----------------------------------------------"

if [ ! -f .env ]; then
    echo "Creating .env configuration..."
    
    # Generate random vault token
    VAULT_TOKEN=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
    echo "VAULT_DEV_ROOT_TOKEN_ID=$VAULT_TOKEN" > .env
    
    echo "Choose your LLM Provider:"
    echo "1) Groq (Default)"
    echo "2) OpenAI"
    echo "3) Anthropic"
    echo "4) OpenRouter"
    echo "5) NVIDIA Build"
    echo "6) Local Model (Ollama/LM Studio)"
    read -p "Select [1-6]: " PROVIDER_SELECTION
    
    MODEL="groq/openai/gpt-oss-120b"
    VAULT_PROVIDER_KEY="groq"
    
    if [ "$PROVIDER_SELECTION" = "2" ]; then
        MODEL="gpt-4o"
        read -p "Enter OpenAI API Key: " API_KEY
        echo "OPENAI_API_KEY=$API_KEY" >> .env
        VAULT_PROVIDER_KEY="openai"
    elif [ "$PROVIDER_SELECTION" = "3" ]; then
        MODEL="claude-3-5-sonnet-20240620"
        read -p "Enter Anthropic API Key: " API_KEY
        echo "ANTHROPIC_API_KEY=$API_KEY" >> .env
        VAULT_PROVIDER_KEY="anthropic"
    elif [ "$PROVIDER_SELECTION" = "4" ]; then
        MODEL="openrouter/auto"
        read -p "Enter OpenRouter API Key: " API_KEY
        echo "OPENROUTER_API_KEY=$API_KEY" >> .env
        VAULT_PROVIDER_KEY="openrouter"
    elif [ "$PROVIDER_SELECTION" = "5" ]; then
        MODEL="nvidia/llama-3.1-70b-instruct"
        read -p "Enter NVIDIA API Key: " API_KEY
        echo "NVIDIA_API_KEY=$API_KEY" >> .env
        VAULT_PROVIDER_KEY="nvidia"
    elif [ "$PROVIDER_SELECTION" = "6" ]; then
        MODEL="openai/local"
        read -p "Enter Local Base URL (e.g. http://localhost:11434/v1): " LOCAL_URL
        echo "OPENAI_API_BASE=$LOCAL_URL" >> .env
        echo "OPENAI_API_KEY=dummy_key" >> .env
        API_KEY="dummy_key"
        VAULT_PROVIDER_KEY="openai"
    else
        read -p "Enter Groq API Key: " API_KEY
        echo "GROQ_API_KEY=$API_KEY" >> .env
    fi
    
    echo "HARNESS_MODEL=$MODEL" >> .env
    echo "VAULT_PROVIDER_KEY=$VAULT_PROVIDER_KEY" >> .env
    echo "PROVIDER_API_KEY=$API_KEY" >> .env
    
    echo ""
    read -p "Enter your Telegram Bot Token: " BOT_TOKEN
    read -p "Enter your Telegram Approval Chat ID: " CHAT_ID
    echo "TELEGRAM_BOT_TOKEN=$BOT_TOKEN" >> .env
    echo "TELEGRAM_APPROVAL_CHAT_ID=$CHAT_ID" >> .env
    
    echo ""
    echo ".env file generated successfully!"
else
    echo "Existing .env found. Continuing..."
fi

echo ""
echo "Starting via Docker Compose..."
docker-compose up --build -d

echo ""
echo "Harness Engine is running! You can view logs with: docker-compose logs -f harness"

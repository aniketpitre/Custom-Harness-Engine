# Harness Engine User Guide

Welcome to Harness Engine! This guide will help you set up and use the agentic framework.

## 1. Setup Wizard

To get started with Harness Engine, use the automated setup wizard. This will configure your API connections for various LLM providers and set up your Telegram bot for approval notifications.

```bash
python3 -m cli.setup
```

The wizard will prompt you for:
- **LLM API Keys**: OpenRouter, Anthropic, OpenAI, NVIDIA, or local options like Ollama/LM Studio.
- **Telegram Integration**: Your bot token and the chat ID for approval notifications.
- **Vault Configuration**: These secrets will be stored in your HashiCorp Vault. Ensure your `VAULT_ADDR` and `VAULT_TOKEN` are set or provisioned via the wizard.

## 2. Using the CLI

You can interact with the Harness Engine directly from your CLI.

```bash
# Example
python3 main.py
```

## 3. Telegram Integration

Once configured with `setup`, the Engine can send approval requests to your Telegram bot.

1. **Bot Creation**: Create a bot via BotFather on Telegram.
2. **Approval Chat ID**: Add the bot to a chat and use a bot to find the ID of that chat.
3. **Execution**: When the engine requires approval (e.g., critical tool calls), it will message you on Telegram with "Approve" and "Deny" buttons.

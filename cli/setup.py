import os
import questionary
from core.secrets import get_vault_client

def setup():
    print("Welcome to Harness Engine Setup!")

    # Simple setup for Telegram
    bot_token = questionary.password("Enter your Telegram Bot Token:").ask()
    chat_id = questionary.text("Enter your Telegram Approval Chat ID:").ask()

    # Write to local mock vault for this example (since we don't have a real vault running)
    client = get_vault_client()
    client.secrets.kv.v2.create_or_update_secret(
        path="telegram",
        secret=dict(bot_token=bot_token, approval_chat_id=chat_id),
        mount_point="harness-secrets",
    )
    print("Telegram secrets saved to Vault.")

    # LLM Providers
    provider = questionary.select(
        "Choose your primary LLM provider:",
        choices=["OpenRouter", "Anthropic", "OpenAI", "NVIDIA", "Local (Ollama/LM Studio)"]
    ).ask()

    if provider != "Local (Ollama/LM Studio)":
        key = questionary.password(f"Enter your {provider} API Key:").ask()
        client.secrets.kv.v2.create_or_update_secret(
            path="llm",
            secret=dict(provider=provider, api_key=key),
            mount_point="harness-secrets",
        )
        print(f"{provider} credentials saved.")

if __name__ == "__main__":
    setup()

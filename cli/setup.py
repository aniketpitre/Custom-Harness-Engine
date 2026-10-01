"""Interactive setup: stores provider and Telegram credentials in Vault and prints next steps."""
import secrets as pysecrets

from core.secrets import get_vault_client

PROVIDERS = {
    "Groq": ("groq", "groq/openai/gpt-oss-120b"),
    "OpenRouter": ("openrouter", "openrouter/auto"),
    "Anthropic": ("anthropic", "anthropic/claude-sonnet-4-5"),
    "OpenAI": ("openai", "openai/gpt-4o"),
    "NVIDIA": ("nvidia", "nvidia_nim/meta/llama-3.1-70b-instruct"),
}


def setup() -> None:
    import questionary  # optional dependency: pip install "penko-perry[setup]"

    print("Welcome to Penko Perry setup!")
    client = get_vault_client()
    mount = "harness-secrets"

    provider_label = questionary.select("Choose your primary LLM provider:", choices=list(PROVIDERS)).ask()
    provider, default_model = PROVIDERS[provider_label]
    key = questionary.password(f"Enter your {provider_label} API key:").ask()
    client.secrets.kv.v2.create_or_update_secret(
        path="llm", secret=dict(provider=provider, api_key=key), mount_point=mount)
    model = questionary.text("Model:", default=default_model).ask()

    token = pysecrets.token_hex(32)
    client.secrets.kv.v2.create_or_update_secret(path="harness", secret=dict(api_token=token), mount_point=mount)

    if questionary.confirm("Configure Telegram approvals?", default=True).ask():
        bot = questionary.password("Telegram bot token:").ask()
        chat = questionary.text("Approval chat id:").ask()
        client.secrets.kv.v2.create_or_update_secret(
            path="telegram", secret=dict(bot_token=bot, approval_chat_id=chat), mount_point=mount)

    print("\nSecrets saved to Vault.")
    print(f"Set PENKO_MODEL={model}")
    print("The API token was stored at harness-secrets/harness (read it with `vault kv get`).")
    print("Start the API with: python main.py")


if __name__ == "__main__":
    setup()

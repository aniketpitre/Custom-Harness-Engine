#!/bin/sh
set -eu

until vault secrets list >/dev/null 2>&1; do
	sleep 1
done

if ! vault secrets list -format=json | grep -q '"harness-secrets/"'; then
	vault secrets enable -path=harness-secrets kv-v2
fi

# We use the explicitly designated VAULT_PROVIDER_KEY and PROVIDER_API_KEY
# so that the Harness Engine can fetch exactly the provider requested.
vault kv put harness-secrets/llm provider="$VAULT_PROVIDER_KEY" api_key="$PROVIDER_API_KEY"
# Keep groq as fallback due to backwards compatibility in some tests/code
if [ -n "${GROQ_API_KEY:-}" ]; then
    vault kv put harness-secrets/groq api_key="$GROQ_API_KEY"
fi

vault kv put harness-secrets/telegram \
	bot_token="$TELEGRAM_BOT_TOKEN" \
	approval_chat_id="$TELEGRAM_APPROVAL_CHAT_ID"

vault kv put harness-secrets/kubernetes kubeconfig_path="/root/.kube/config"

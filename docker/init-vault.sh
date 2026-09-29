#!/bin/sh
set -eu

until vault secrets list >/dev/null 2>&1; do
	sleep 1
done

if ! vault secrets list -format=json | grep -q '"harness-secrets/"'; then
	vault secrets enable -path=harness-secrets kv-v2
fi

# LLM provider credential: resolved per model by the harness (provider name must match the model prefix).
if [ -n "${PROVIDER_API_KEY:-}" ]; then
	vault kv put harness-secrets/llm provider="$VAULT_PROVIDER_KEY" api_key="$PROVIDER_API_KEY"
elif [ -n "${GROQ_API_KEY:-}" ]; then
	vault kv put harness-secrets/llm provider="groq" api_key="$GROQ_API_KEY"
fi

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_APPROVAL_CHAT_ID:-}" ]; then
	vault kv put harness-secrets/telegram bot_token="$TELEGRAM_BOT_TOKEN" approval_chat_id="$TELEGRAM_APPROVAL_CHAT_ID"
fi

vault kv put harness-secrets/harness api_token="$HARNESS_API_TOKEN"
vault kv put harness-secrets/kubernetes kubeconfig_path="/home/harness/.kube/config"

# Least privilege: the harness may only READ secrets under harness-secrets/.
vault policy write harness-read - <<'POLICY'
path "harness-secrets/data/*" { capabilities = ["read"] }
path "harness-secrets/metadata/*" { capabilities = ["list", "read"] }
POLICY
umask 022
vault token create -policy=harness-read -period=768h -field=token > /run/harness/vault_token
echo "harness token written"

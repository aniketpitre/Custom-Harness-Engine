#!/bin/sh
set -eu

until vault secrets list >/dev/null 2>&1; do
	sleep 1
done

if ! vault secrets list -format=json | grep -q '"harness-secrets/"'; then
	vault secrets enable -path=harness-secrets kv-v2
fi

vault kv put harness-secrets/groq api_key="$GROQ_API_KEY"
vault kv put harness-secrets/telegram \
	bot_token="$TELEGRAM_BOT_TOKEN" \
	approval_chat_id="$TELEGRAM_APPROVAL_CHAT_ID"
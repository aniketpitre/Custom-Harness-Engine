# Local Docker deployment

This Compose deployment starts a development-only Vault server, initializes the
`harness-secrets` KV mount with the Groq credential, and then runs the harness.
The harness container receives Vault connection settings, not the Groq key.

Create the ignored local environment file and fill it in directly in your
terminal:

```bash
cp .env.example .env
$EDITOR .env
```

Then start the stack:

```bash
docker compose up --build
```

The `harness` service runs the real CLI scenario after `vault-init` completes.
The JSON run receipt is printed in the Compose output.

This uses Vault dev mode and is for local development only. Dev-mode Vault
data is not persistent and the root token is not suitable for production.
Production should use an external persistent Vault deployment with TLS and a
least-privileged policy.
# Docker deployment

`./start.sh` (or `docker compose up --build`) starts:

1. **vault** - development-mode Vault, published on `127.0.0.1:8200` only.
2. **vault-init** - seeds `harness-secrets/` with the root token, writes a `harness-read` policy and mints a
   **read-only, renewable token** into a shared volume. Penko Perry receives only that token file
   (`VAULT_TOKEN_FILE`) - never the root token and never the raw provider key.
3. **penko** - the API on `127.0.0.1:8000` (host loopback), non-root user, health-checked, persistent
   `/app/data`, and a separate `/workspace` volume that is the only directory file/shell tools can touch.

```bash
cp .env.example .env && chmod 600 .env && $EDITOR .env     # or run ./start.sh to generate it
docker compose up --build -d
curl -H "Authorization: Bearer $PENKO_API_TOKEN" http://127.0.0.1:8000/agents
docker compose run --rm penko penko run "List the files in the workspace"
```

Vault dev mode is **not persistent and not for production**. Production: an external Vault with TLS,
a least-privilege policy per environment, and short-lived tokens. To use Kubernetes tools, mount a
read-only kubeconfig (commented in `docker-compose.yml`).

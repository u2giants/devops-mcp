# Token management

## Concept

Each AI tool that connects to this server has its own bearer token. Tokens are
named after the *tool* (e.g. Roo Code), not the underlying AI model (e.g. GPT-4),
because the same tool might switch models. The audit log records the tool name,
not the model.

## Current tokens

| Agent name | Env var | Token |
|---|---|---|
| claude | `TOKEN_CLAUDE` | `wl6Uxf9dlZ981eNF_d8M7EQXbkI56fvtZV-5i0nWa0k` |
| gemini | `TOKEN_GEMINI` | `TpZbQejvI3Wfu9i99rDgLnAnr8BLLWgihsT-oY0NP6E` |
| chatgpt | `TOKEN_CHATGPT` | `z_RV85gZIUd4mN6xaQ3-puPnCuVzVX6GIcsZ_jYqMpk` |
| codex | `TOKEN_CODEX` | `0Aaq7Qxb4EezlZBn0eOqy-b0XErOP8AcvfUNJ8V1cFc` |
| roocode | `TOKEN_ROOCODE` | `xBY2IHFwVfXnVUZ3rwfs-zW0jdf4BO2oO8iB1TjRs-0` |

> **Keep this file updated** when tokens are added, removed, or rotated.

## How to give a new AI tool access

1. **Generate a token:**
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **Record it** in the table above, in the `docker run` command in
   [deployment.md](deployment.md), and in Coolify's env vars.

3. **Add to Coolify** (so it's stored there as a record):
   ```bash
   curl -X POST http://127.0.0.1:8000/api/v1/services/vj5f76xet05bxwdq4utw1kho/envs \
     -H "Authorization: Bearer <coolify_api_token>" \
     -H "Content-Type: application/json" \
     -d '{"key":"TOKEN_MYTOOL","value":"<generated_token>"}'
   ```

4. **Restart the container** with the new token added as `-e TOKEN_MYTOOL=...`
   (re-run the full `docker run` command from [deployment.md](deployment.md)).

5. **Give to the AI tool:** The MCP connection config is:
   - URL: `https://mcp.designflow.app/mcp`
   - Header: `Authorization: Bearer <that-tool's-token>`

## Revoking a token

Remove the `-e TOKEN_NAME=...` from the `docker run` command and re-run it.
The token stops working immediately on restart. The old entries in the audit log
keep showing the agent name — that's fine, they're historical.

## Token security

- Tokens are 32-byte random URL-safe strings (256 bits of entropy). Unguessable.
- They travel over HTTPS only — Traefik terminates TLS before traffic reaches the
  container.
- Anyone with a token has **full root-equivalent access** to the server. Treat tokens
  like passwords. Do not share, do not commit to git.
- Tokens are currently stored in plaintext in env vars. There is no server-side
  hashing. If the server is compromised, tokens are exposed. This is an acceptable
  tradeoff given the server already has full host access.

## Rotating a token

If a token is exposed or you want to rotate it for any reason:
1. Generate a new token
2. Update the AI tool's MCP config with the new token
3. Update the `docker run` command
4. Restart the container
5. The old token stops working immediately

## Future improvement: file-based tokens

Currently tokens are loaded from env vars at container startup. To add a token you
must restart the container (brief downtime). A future improvement would be to load
tokens from a JSON file mounted as a volume, with a file-watcher that reloads on
change — no restart needed. This would make token management much simpler.

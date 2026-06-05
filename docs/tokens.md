# Token management

## Concept

Each AI client gets its own bearer token. Tokens are named after the client/tool,
not the underlying model, because a client can switch models. The audit log records
the lowercased name from the `TOKEN_<NAME>` variable.

## Configured agent names

Do not store token values in this file.

| Agent name | Env var | Stored where |
|---|---|---|
| `claude` | `TOKEN_CLAUDE` | Coolify env |
| `gemini` | `TOKEN_GEMINI` | Coolify env |
| `chatgpt` | `TOKEN_CHATGPT` | Coolify env |
| `codex` | `TOKEN_CODEX` | Coolify env |
| `roocode` | `TOKEN_ROOCODE` | Coolify env |

## Add a new AI client

1. Generate a token:
   ```sh
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Add `TOKEN_<NAME>=<generated-token>` in Coolify under the DevOps MCP service.
3. Restart/redeploy the service so the process reads the new environment.
4. Configure the client with:
   - URL: `https://mcp.designflow.app/mcp`
   - Header: `Authorization: Bearer <generated-token>`

## Revoke or rotate a token

1. Remove or replace the `TOKEN_<NAME>` value in Coolify.
2. Restart/redeploy the DevOps MCP service.
3. Update the affected MCP client configuration.

Old audit entries keep the old agent name; that is expected historical data.

## Security notes

- Anyone with a valid token has root-equivalent VPS access through this MCP server.
- Tokens are plaintext environment variables in Coolify.
- Never commit token values, screenshots of token values, or copied client config
  containing token values.

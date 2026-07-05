# Configuration

Runtime configuration lives in Coolify environment variables for the production
service. Do not commit secret values.

## MCP server

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PORT` | yes in prod | `8765` | Uvicorn listen port |
| `BIND_HOST` | no | `0.0.0.0` | Uvicorn bind host |
| `HOST_ROOT` | yes in prod | `/host` | Container path for host root filesystem |
| `AUDIT_LOG_PATH` | yes in prod | `/audit/mcp-audit.log` | JSONL audit log file |
| `MAX_OUTPUT_CHARS` | no | `60000` | Max command output returned to clients |
| `DEFAULT_TIMEOUT` | no | `120` | Default host command timeout in seconds |

## Agent tokens

Every `TOKEN_<NAME>` env var creates one valid bearer token and maps audit records
to `<name>` lowercased. Current configured agent names are documented without
secret values in `docs/tokens.md`.

| Variable | Purpose |
|---|---|
| `TOKEN_CLAUDE` | Claude clients |
| `TOKEN_GEMINI` | Gemini clients |
| `TOKEN_CHATGPT` | ChatGPT clients |
| `TOKEN_CODEX` | Codex clients |
| `TOKEN_ROOCODE` | Roo Code clients |

If no `TOKEN_*` variables are set, the server logs a warning and no authenticated
agent can use the MCP endpoint.

## Cloudflare Tunnel

| Variable | Required | Purpose |
|---|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | yes | Tunnel for `mcp.designflow.app` |
| `CF_GW_TUNNEL_TOKEN` | yes if ContextForge tunnel is enabled | Tunnel for the ContextForge sidecar |

## ContextForge sidecar

| Variable | Required if ContextForge is enabled | Purpose |
|---|---|---|
| `CF_JWT_SECRET` | yes | ContextForge JWT signing |
| `CF_AUTH_SECRET` | yes | ContextForge auth encryption |
| `CF_ADMIN_EMAIL` | yes | Platform admin email and registration username |
| `CF_ADMIN_PASSWORD` | yes | Platform admin password/basic auth password |

`contextforge-register` uses `TOKEN_CLAUDE` as the bearer token for registering
`http://devops-mcp:8765/mcp` with the ContextForge gateway.

## GitHub Actions secrets

Set on `u2giants/devops-mcp`.

| Secret | Purpose |
|---|---|
| `GITHUB_TOKEN` | Automatic; pushes images to GHCR |
| `COOLIFY_API_TOKEN` | Authenticates the deploy API call |
| `COOLIFY_BASE_URL` | Coolify API base URL |
| `COOLIFY_SERVICE_UUID` | Coolify service UUID to deploy |

Legacy SSH secrets may still exist in GitHub, but the current workflow does not
use them.

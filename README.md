# DevOps MCP Server

MCP server that gives AI agents full access to the VPS for devops and sysadmin tasks.

**Live URL:** `https://mcp.designflow.app/mcp`  
**SSE URL:** `https://mcp.designflow.app/sse/sse?token=YOUR_TOKEN_HERE`  
**Status page:** `https://mcp.designflow.app/`

---

## Documentation

| Doc | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How all the pieces fit together, nsenter, middleware, Traefik |
| [docs/server.md](docs/server.md) | Every section of server.py explained |
| [docs/deployment.md](docs/deployment.md) | The `docker run` command, adding tokens, networking, volumes |
| [docs/cicd.md](docs/cicd.md) | GitHub Actions pipeline, image tags, known limitations |
| [docs/tokens.md](docs/tokens.md) | Current token list, how to add/revoke agents |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems and how to fix them |
| [docs/gotchas.md](docs/gotchas.md) | Things that will bite you — read before making changes |

---

## What it does

Connects any AI tool (Claude, Gemini, ChatGPT, etc.) to the server via the
[Model Context Protocol](https://modelcontextprotocol.io). The AI can then run
commands, manage Docker containers, edit files, restart services, and more —
exactly as if it had SSH root access, but with an audit log of every action.

---

## Available tools

| Tool | What it does |
|---|---|
| `run_command` | Run any shell command on the host (docker, systemctl, apt, etc.) |
| `read_file` | Read any file from the host filesystem |
| `write_file` | Write/edit any file (auto-backup of originals) |
| `list_directory` | Browse the filesystem |
| `docker_ps` | List containers |
| `docker_logs` | Get container logs |
| `docker_action` | Restart / stop / start a container |
| `service_status` | Check systemd service status |
| `service_action` | Start / stop / restart a systemd service |
| `view_audit_log` | See who did what and when |
| `health` | Server info and registered agents |

---

## Authentication

Every AI agent gets its own bearer token. Tokens are set as environment variables
in Coolify: `TOKEN_<NAME>=<secret>`.

| Agent | Variable |
|---|---|
| Claude | `TOKEN_CLAUDE` |
| Gemini | `TOKEN_GEMINI` |
| ChatGPT | `TOKEN_CHATGPT` |
| Codex | `TOKEN_CODEX` |

To add a new agent: add `TOKEN_<NAME>=<secret>` in Coolify → Environment Variables → Restart.

### How to connect an AI tool

Every MCP client needs two things:
- **URL:** `https://mcp.designflow.app/mcp`
- **Header:** `Authorization: Bearer <that-agent's-token>`

The header is configured once in the AI tool's settings. After that the AI sends it
automatically with every request.

For Windsurf and Roo Code, use the SSE setup documented in
[docs/windsurf-roo-setup.md](docs/windsurf-roo-setup.md).

---

## Audit log

Every tool call is logged to `/audit/mcp-audit.log` inside the container (persisted
in the `mcp-audit` Docker volume). Each line is a JSON record:

```json
{"ts": "2026-04-06T14:53:09Z", "agent": "claude", "tool": "run_command", "args": {"command": "docker ps"}, "ok": true, "duration_ms": 111}
```

To view recent activity, ask any connected AI: *"show me the last 50 audit log entries"*

---

## CI/CD

Push to `main` → GitHub Actions builds and pushes to GHCR → Coolify restarts the
container with the new image. No branches, no PRs.

- Image: `ghcr.io/u2giants/devops-mcp:main`
- Also tagged: `ghcr.io/u2giants/devops-mcp:sha-<commit>`

---

## Coolify management

The service lives in Coolify under **DevOps MCP → production**.

- **Restart:** Coolify UI → service → Restart button
- **Logs:** Coolify UI → service → Logs
- **Add/change tokens:** Coolify UI → service → Environment Variables → add `TOKEN_<NAME>` → Save → Restart
- **Deploy latest:** push to `main` (automatic) or Coolify → Redeploy

---

## Architecture

The container runs with:
- `privileged: true` — full Linux capabilities
- `pid: host` — shares the host PID namespace (needed for `nsenter` to run commands on host)
- `/:/host` — host root filesystem mounted at `/host`
- `/var/run/docker.sock` — host Docker socket (for Docker management)

Commands are executed on the host via `nsenter --target 1 --mount --uts --ipc --net --pid`.
File operations transparently prefix paths with `/host`.

The server detects it is inside a container via `/.dockerenv` and switches to host-access
mode automatically.

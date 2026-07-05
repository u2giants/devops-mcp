# Architecture

## What this system is

A server that lets AI tools (Claude, Gemini, ChatGPT, Roo Code, etc.) inspect and,
when necessary, repair the VPS over the internet — running commands, managing Docker
containers, editing files, restarting services — as if they had SSH root access.

That root-equivalent access is for diagnostics and break-glass repair, not normal
configuration management. Durable host/OS changes are owned by `/worksp/ansible`
([u2giants/ansible](https://github.com/u2giants/ansible)) and should be made as
Ansible PRs applied by GitHub Actions.

The protocol that carries these instructions is called
[MCP (Model Context Protocol)](https://modelcontextprotocol.io), which is now supported
by most major AI tools. The AI connects to the MCP server, calls a "tool" (like
`run_command` or `restart_service`), and the server executes it on the host.

---

## Bird's-eye view

```
AI tool (Claude, Gemini, Roo Code, Windsurf, etc.)
    │
    │  HTTPS POST  ── Authorization: Bearer <token>  OR  ?token=<secret>
    ▼
Cloudflare DNS (mcp.designflow.app → proxied CNAME → Cloudflare Tunnel)
    │
    ▼
cloudflared sidecar container  (tunnels traffic into the VPS)
    │
    ▼
devops-mcp Docker container  (port 8765)
    │
    ├── Auth middleware   checks Bearer token or ?token= → maps to agent name
    ├── Audit middleware  logs every tool call to /audit/mcp-audit.log
    ├── FastMCP server    speaks MCP Streamable HTTP, exposes tools
    │
    ├── nsenter ──────────────────────────────────────────────────────┐
    │   (enters host PID/mount/net namespaces)                        │
    │                                                             HOST SYSTEM
    ├── /var/run/docker.sock ─────────────────────────────────── Docker daemon
    └── /host (= host's /) ───────────────────────────────────── Full filesystem
```

Sidecar in the same Docker Compose stack:
```
contextforge-register  (sidecar container)
    │
    │  Registers tools with ContextForge platform
    ▼
ContextForge cloud  (external service)
```

---

## Key components

### 1. The MCP server (Python, FastMCP)

`server.py` — a Python process using the [FastMCP](https://gofastmcp.com) library.
FastMCP handles the MCP wire protocol (JSON-RPC over Streamable HTTP). The server defines
"tools" — Python functions that the AI can call.

Runs inside a Docker container. Listens on port 8765.

### 2. Docker container (privileged, pid:host)

The container has special permissions that let it act on the host:

| Config | Why it's needed |
|---|---|
| `privileged: true` | Full Linux capabilities, required for nsenter |
| `pid: host` | Shares the host's PID namespace — PID 1 is the host's init process |
| `/:/host` volume | Host root filesystem readable/writable at `/host` inside container |
| `/var/run/docker.sock` | Docker socket — lets the container manage host Docker |

### 3. nsenter — how host commands work

When you call `run_command("systemctl restart nginx")`, the server doesn't run that
inside the container (which has no systemd). Instead it uses `nsenter`:

```
nsenter --target 1 --mount --uts --ipc --net --pid -- bash -c "systemctl restart nginx"
```

`--target 1` means "enter the namespaces of PID 1" — which, because we're running
with `pid: host`, is the host's init process. The command therefore runs as if typed
directly on the host.

This only works because:
- The container has `pid: host` (so PID 1 is the real host init)
- The container has `privileged: true` (so nsenter has permission to enter namespaces)

### 4. Authentication (ASGI middleware)

Every authenticated request must include either `Authorization: Bearer <token>`
or `?token=<token>` in the URL.

Tokens are environment variables named `TOKEN_<NAME>`:
- `TOKEN_CLAUDE=abc...` → agent name `claude`
- `TOKEN_ROOCODE=xyz...` → agent name `roocode`

At startup the server reads all `TOKEN_*` env vars into a dict `{token: agent_name}`.
The ASGI middleware checks the `Authorization` header first, then falls back to the
`token` query parameter and rejects unknown tokens.

### 4.1 Transport endpoint

The server exposes a single transport:
- Streamable HTTP at `/mcp`

All clients (Windsurf, Roo Code, Claude, Gemini, ChatGPT, Codex) connect via
`POST /mcp` using Streamable HTTP. Auth is via `Authorization: Bearer <token>`
header or `?token=` query parameter.

The status page at `/` and `/status` is exempt from auth — it's public and read-only.

### 5. Audit logging (FastMCP middleware)

A second middleware layer, operating at the MCP protocol level (not HTTP), intercepts
every tool call. It records:
- Timestamp (UTC)
- Agent name (from auth middleware, passed via Python `contextvars`)
- Tool name
- Arguments passed
- Whether it succeeded
- Duration in milliseconds

Written as JSON lines to `/audit/mcp-audit.log`, which is in a named Docker volume
(`vj5f76xet05bxwdq4utw1kho_mcp-audit`) that survives container restarts.

### 6. Two middleware layers — how they communicate

There's a subtlety: auth happens at the HTTP (ASGI) layer, but audit logging happens
at the MCP protocol layer. These are separate middleware systems with no direct link.

The bridge is a Python `contextvars.ContextVar`:

```python
current_agent: ContextVar[str] = ContextVar("current_agent", default="unknown")
```

The ASGI auth middleware calls `current_agent.set("claude")` when a request comes in.
The FastMCP audit middleware calls `current_agent.get()` when a tool is called.
Because FastMCP processes the MCP request in the same async context as the HTTP
request, the contextvar carries the agent identity through.

### 7. Cloudflare Tunnel routing

Public traffic reaches the container through a **Cloudflare Tunnel** (cloudflared
sidecar), not through Traefik. The domain `mcp.designflow.app` is a proxied CNAME
pointing to the tunnel ID in Cloudflare DNS — there is no direct A record to the VPS IP.

The container still has Traefik labels (from Coolify), but they are not used for
public traffic routing. Traefik/Coolify proxy plays no role in routing HTTPS requests
to this service.

The tunnel forwards HTTPS traffic directly to the container on port 8765 inside
the Docker network.

### 7.1. ContextForge sidecar

The `contextforge-register` container is a sidecar defined in the same
`docker-compose.yml` stack. It is **not** the MCP server and does not handle
AI client connections. Its sole job is to register the MCP server's tools
with the ContextForge platform so they appear in the ContextForge UI.

| Property | Value |
|---|---|
| Image | `ghcr.io/u2giants/contextforge-register` |
| Connects to | `http://devops-mcp:8765/mcp` (internal Docker network) |
| Transport | `STREAMABLEHTTP` |
| Direction | Outbound only — pushes tool metadata to ContextForge cloud |

If the ContextForge registration fails, it does not affect the MCP server's
ability to serve AI clients. The sidecar is fire-and-forget at startup.

### 8. CI/CD

Push to `main` on GitHub → GitHub Actions builds a Docker image → pushes to
`ghcr.io/u2giants/devops-mcp:main` → calls Coolify API to restart the service.

See [cicd.md](cicd.md) for full details.

---

## What this system is NOT

- **Not a firewall or security layer.** Any agent with a valid token can do anything.
  The auth is about identity/logging, not access control.
- **Not the source of truth for host configuration.** Packages, users, firewall,
  SSH/sudo, Docker engine or daemon config, systemd units/timers, cron, `/etc`,
  `/usr/local/bin`, `/usr/local/sbin`, Cloudflare Tunnel 1, Coolify host glue, and
  the backup/DNS watchdogs belong in `/worksp/ansible`. Break-glass direct repairs
  must be followed by an Ansible PR to capture or reconcile drift. Warn-mode policy
  reminders do not replace that PR/apply flow.
- **Not a place for live source edits.** Coolify manages the running compose
  service, but GitHub remains the source of truth. Source changes go through
  GitHub Actions, GHCR, and the Coolify API deploy trigger.
- **Not stateless.** The audit log volume persists data. The `/host` mount means file
  writes made through this server are permanent on the host.

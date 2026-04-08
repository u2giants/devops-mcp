# Architecture

## What this system is

A server that lets AI tools (Claude, Gemini, ChatGPT, Roo Code, etc.) control the VPS
over the internet — installing software, managing Docker containers, editing files,
restarting services — as if they had SSH root access.

The protocol that carries these instructions is called
[MCP (Model Context Protocol)](https://modelcontextprotocol.io), which is now supported
by most major AI tools. The AI connects to the MCP server, calls a "tool" (like
`run_command` or `restart_service`), and the server executes it on the host.

---

## Bird's-eye view

```
AI tool (Claude, Gemini, Roo Code, etc.)
    │
    │  HTTPS  ── Authorization: Bearer <token>
    ▼
Cloudflare DNS (mcp.designflow.app → 178.156.180.212)
    │
    ▼
Traefik (coolify-proxy container, port 443)
    │  routes Host: mcp.designflow.app to container
    ▼
devops-mcp Docker container  (port 8765 inside coolify network)
    │
    ├── Auth middleware   checks Bearer token or ?token= → maps to agent name
    ├── Audit middleware  logs every tool call to /audit/mcp-audit.log
    ├── FastMCP server    speaks MCP protocol, exposes tools
    │
    ├── nsenter ──────────────────────────────────────────────────────┐
    │   (enters host PID/mount/net namespaces)                        │
    │                                                             HOST SYSTEM
    ├── /var/run/docker.sock ─────────────────────────────────── Docker daemon
    └── /host (= host's /) ───────────────────────────────────── Full filesystem
```

---

## Key components

### 1. The MCP server (Python, FastMCP)

`server.py` — a Python process using the [FastMCP](https://gofastmcp.com) library.
FastMCP handles the MCP wire protocol (JSON-RPC over HTTP/SSE). The server defines
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

### 4.1 Dual transport endpoints

The server exposes both transports:
- HTTP at `/mcp`
- SSE at `/sse`

Windsurf and Roo Code can connect using the SSE URL with `?token=`. Existing HTTP
clients continue using the bearer-token header on `/mcp`.

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

### 7. Traefik routing

The container is on the `coolify` Docker network. Traefik (the `coolify-proxy`
container) watches Docker for containers with `traefik.enable=true` labels and
automatically routes HTTPS traffic to them.

The container's labels configure:
- HTTP → HTTPS redirect
- HTTPS routing for `Host: mcp.designflow.app`
- Let's Encrypt TLS certificate (via `certresolver: letsencrypt`)
- Target port 8765

### 8. CI/CD

Push to `main` on GitHub → GitHub Actions builds a Docker image → pushes to
`ghcr.io/u2giants/devops-mcp:main` → calls Coolify API to restart the service.

See [cicd.md](cicd.md) for full details.

---

## What this system is NOT

- **Not a firewall or security layer.** Any agent with a valid token can do anything.
  The auth is about identity/logging, not access control.
- **Not managed by Coolify's UI.** The container is started with `docker run` manually.
  Coolify can see it (it has Coolify labels) but does not control its lifecycle.
  See [deployment.md](deployment.md) for why and what this means operationally.
- **Not stateless.** The audit log volume persists data. The `/host` mount means file
  writes made through this server are permanent on the host.

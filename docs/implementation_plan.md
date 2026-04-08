# Implementation Plan: Windsurf/Roo MCP Compatibility

## Problem

The devops-mcp server currently only exposes a **stateless HTTP transport** with `Authorization: Bearer <token>` header authentication. Windsurf's MCP client supports **SSE transport** via `serverUrl` but **cannot send custom HTTP headers** (no `Authorization` header support in its config schema). This means Windsurf cannot connect to the server at all.

Roo Code *can* send custom headers, but supporting a header-free auth path benefits all clients and simplifies configuration.

## Solution

Add a **dual-transport architecture** to [`server.py`](server.py):

1. **Keep the existing `/mcp` endpoint** — stateless HTTP with bearer-token auth (unchanged for Claude, Gemini, ChatGPT, Codex)
2. **Add a new `/sse` endpoint** — SSE transport with query-parameter token auth for Windsurf and Roo Code
3. **Unify auth** — the existing `AuthMiddleware` learns to accept tokens from *either* the `Authorization` header *or* a `?token=` query parameter
4. **Agent identity flows through unchanged** — `current_agent` contextvar continues to bridge ASGI→MCP layers

No new files. No new dependencies. One file changed ([`server.py`](server.py)), one file updated ([`docs/tokens.md`](docs/tokens.md)), new doc added.

---

## Architecture After Change

```
Windsurf / Roo Code                    Claude / Gemini / ChatGPT / Codex
    │                                       │
    │  SSE  ?token=<secret>                 │  HTTP  Authorization: Bearer <token>
    ▼                                       ▼
https://mcp.designflow.app/sse        https://mcp.designflow.app/mcp
    │                                       │
    └──────────────┬────────────────────────┘
                   ▼
         AuthMiddleware (accepts both header and query param)
                   │
                   ▼  current_agent contextvar
         AuditMiddleware (logs every tool call)
                   │
                   ▼
         FastMCP server (same tools for all transports)
```

---

## Step-by-Step Tasks

### Task 1: Modify `AuthMiddleware` to accept query-parameter tokens

**File:** [`server.py`](server.py:106) — `AuthMiddleware` class

**Current behavior:** Only checks `Authorization: Bearer <token>` header.

**New behavior:** Check header first; if absent, check `?token=<value>` query parameter. Both map to the same `TOKENS` dict.

```python
PUBLIC_PATHS = {"/", "/status"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Try Authorization header first (existing clients)
        token = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]

        # Fall back to query parameter (Windsurf, Roo Code SSE)
        if token is None:
            token = request.query_params.get("token")

        if token is None:
            return JSONResponse(
                {"error": "Missing auth: provide Authorization header or ?token= param"},
                status_code=401,
            )

        agent = TOKENS.get(token)
        if agent is None:
            return JSONResponse({"error": "Invalid token"}, status_code=403)

        current_agent.set(agent)
        response = await call_next(request)
        return response
```

**Key points:**
- Header auth takes priority (if both are present, header wins)
- Same `TOKENS` dict, same agent resolution, same `current_agent.set()`
- Audit logging works identically — it reads `current_agent.get()` regardless of how auth happened
- Error message updated to mention both auth methods

---

### Task 2: Add SSE transport endpoint

**File:** [`server.py`](server.py:590) — `create_app()` function

**Current `create_app()`** creates one MCP app with `transport="http"` and mounts it.

**New `create_app()`** creates **two** MCP ASGI apps from the same `mcp` FastMCP instance — one for HTTP, one for SSE — and mounts them at different paths.

```python
def create_app() -> Starlette:
    """Create the Starlette ASGI app with status page, HTTP MCP, and SSE MCP."""
    asgi_middleware = []
    if TOKENS:
        asgi_middleware.append(ASGIMiddleware(AuthMiddleware))

    # Existing: stateless HTTP transport at /mcp
    http_app = mcp.http_app(
        stateless_http=True,
        transport="http",
        middleware=asgi_middleware,
    )

    # New: SSE transport at /sse
    sse_app = mcp.http_app(
        transport="sse",
        middleware=asgi_middleware,
    )

    app = Starlette(
        routes=[
            Route("/", status_page),
            Route("/status", status_page),
            Mount("/sse", app=sse_app),
            Mount("/", app=http_app),
        ],
        middleware=asgi_middleware,
        lifespan=http_app.router.lifespan_context,
    )
    return app
```

**Key points:**
- `Mount("/sse", ...)` must come **before** `Mount("/", ...)` in the routes list so Starlette matches `/sse` first
- Both apps share the same `mcp` FastMCP instance — same tools, same MCP-level audit middleware
- Both apps get the same ASGI auth middleware — token validation works on both
- The SSE app does NOT use `stateless_http=True` — SSE is inherently stateful (long-lived connection)
- FastMCP's `http_app(transport="sse")` creates the standard MCP SSE endpoint that Windsurf expects

**Important FastMCP SSE behavior:** When `transport="sse"`, FastMCP creates:
- `GET /sse` — the SSE stream endpoint (client connects here)
- `POST /messages` — the message endpoint (client sends JSON-RPC here)

Since we mount at `/sse`, the actual paths become:
- `GET /sse/sse` — SSE stream
- `POST /sse/messages` — messages

Windsurf's `serverUrl` should point to `https://mcp.designflow.app/sse/sse`. However, this double-`/sse/sse` is ugly. **Alternative:** mount at `/` with a path prefix in the SSE app, or mount the SSE app at `/sse` and let FastMCP handle sub-routing. The Builder should test this and verify the exact URL Windsurf needs.

**Simpler alternative if double-path is a problem:** Mount the SSE app at `/stream` so the SSE endpoint becomes `/stream/sse` — cleaner URL.

---

### Task 3: Update `PUBLIC_PATHS` for SSE handshake

**File:** [`server.py`](server.py:104)

The SSE endpoint paths should NOT be in `PUBLIC_PATHS` — they require auth. But verify that the auth middleware correctly intercepts SSE `GET` requests (not just `POST`). The current middleware runs on all non-public paths regardless of HTTP method, so this should work without changes.

No code change needed here — just verification during testing.

---

### Task 4: Add `/sse` to status page info (optional enhancement)

**File:** [`server.py`](server.py:470) — `status_page()` function

Add a line to the status page HTML showing both endpoints:

```html
<p class="subtitle">
  mcp.designflow.app &nbsp;·&nbsp;
  HTTP: /mcp &nbsp;·&nbsp; SSE: /sse &nbsp;·&nbsp;
  refreshes every 30s
</p>
```

This is a minor cosmetic change — low priority.

---

### Task 5: Update documentation

#### 5a. New file: `docs/windsurf-roo-setup.md`

Create a new doc with client configuration examples:

```markdown
# Windsurf & Roo Code Setup

## Windsurf Configuration

Add to your Windsurf `mcp_config.json` (usually at `~/.codeium/windsurf/mcp_config.json`):

{
  "mcpServers": {
    "devops-mcp": {
      "serverUrl": "https://mcp.designflow.app/sse/sse?token=YOUR_TOKEN_HERE"
    }
  }
}

Replace `YOUR_TOKEN_HERE` with your agent token (see docs/tokens.md).

## Roo Code Configuration

Roo Code supports both SSE and HTTP transports. You can use either:

### Option A: SSE (recommended — same as Windsurf)

In Roo Code MCP settings, add a server with:
- Transport: SSE
- URL: `https://mcp.designflow.app/sse/sse?token=YOUR_TOKEN_HERE`

### Option B: HTTP with header (existing method)

In Roo Code MCP settings, add a server with:
- Transport: HTTP
- URL: `https://mcp.designflow.app/mcp`
- Headers: `Authorization: Bearer YOUR_TOKEN_HERE`

## Security Note

The token appears in the URL when using query-parameter auth. This is acceptable
because:
- The connection is over HTTPS (TLS encrypted end-to-end)
- Cloudflare Tunnel provides additional transport security
- The token is not logged by Cloudflare or Traefik in the default configuration
- Server access logs do not record query parameters

However, be aware that the token may appear in browser history, proxy logs, or
Cloudflare analytics if URL logging is enabled. For maximum security, use the
header-based auth method when the client supports it.
```

#### 5b. Update [`docs/tokens.md`](docs/tokens.md)

Add a section at the bottom:

```markdown
## Connecting from Windsurf or Roo Code

These clients use SSE transport with query-parameter auth instead of HTTP + header.
See [windsurf-roo-setup.md](windsurf-roo-setup.md) for configuration examples.
```

#### 5c. Update [`CLAUDE.md`](CLAUDE.md)

Add to the docs table:

```markdown
| [docs/windsurf-roo-setup.md](docs/windsurf-roo-setup.md) | Windsurf & Roo Code MCP config |
```

Add to quick reference:

```markdown
| SSE endpoint | `https://mcp.designflow.app/sse/sse` |
```

#### 5d. Update [`docs/architecture.md`](docs/architecture.md)

Update the bird's-eye view diagram to show both transports. Update section 4 (Authentication) to mention query-parameter auth.

---

### Task 6: No changes needed to these files

| File | Why no change |
|---|---|
| [`requirements.txt`](requirements.txt) | FastMCP >=2.14.0 already supports SSE transport natively |
| [`Dockerfile`](Dockerfile) | No new dependencies, no new ports |
| [`docker-compose.yml`](docker-compose.yml) | Same port 8765, same container config. No new env vars needed — existing `TOKEN_*` vars work for both transports |

---

## Validation Approach

### Manual Testing Checklist

1. **Existing HTTP transport still works:**
   ```bash
   curl -X POST https://mcp.designflow.app/mcp \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
   ```
   Expected: 200 OK with tool list

2. **SSE endpoint responds:**
   ```bash
   curl -N "https://mcp.designflow.app/sse/sse?token=<token>"
   ```
   Expected: SSE stream opens (content-type: text/event-stream)

3. **SSE without token is rejected:**
   ```bash
   curl -N "https://mcp.designflow.app/sse/sse"
   ```
   Expected: 401 Unauthorized

4. **HTTP without token is still rejected:**
   ```bash
   curl -X POST https://mcp.designflow.app/mcp \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
   ```
   Expected: 401 Unauthorized

5. **Query param works on HTTP endpoint too (bonus):**
   ```bash
   curl -X POST "https://mcp.designflow.app/mcp?token=<token>" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
   ```
   Expected: 200 OK (the auth middleware accepts query params on all paths)

6. **Audit log records agent identity for SSE connections:**
   After making a tool call via SSE, check `/audit/mcp-audit.log` — the `agent` field should show the correct agent name, not "unknown"

7. **Windsurf end-to-end:** Configure Windsurf with the SSE URL + token, verify it discovers tools and can call `health()`

8. **Roo Code end-to-end:** Configure Roo Code with the SSE URL + token, verify it discovers tools and can call `health()`

### Automated Smoke Test (optional)

The Builder may add a simple Python script that tests both endpoints:

```python
# test_endpoints.py — run after deployment
import httpx, sys

BASE = "https://mcp.designflow.app"
TOKEN = sys.argv[1]

# Test HTTP with header
r = httpx.post(f"{BASE}/mcp", headers={"Authorization": f"Bearer {TOKEN}"},
               json={"jsonrpc":"2.0","method":"tools/list","id":1})
assert r.status_code == 200, f"HTTP failed: {r.status_code}"

# Test HTTP with query param
r = httpx.post(f"{BASE}/mcp?token={TOKEN}",
               json={"jsonrpc":"2.0","method":"tools/list","id":1})
assert r.status_code == 200, f"HTTP query param failed: {r.status_code}"

# Test SSE endpoint opens
with httpx.stream("GET", f"{BASE}/sse/sse?token={TOKEN}") as r:
    assert r.status_code == 200, f"SSE failed: {r.status_code}"

# Test auth rejection
r = httpx.post(f"{BASE}/mcp", json={"jsonrpc":"2.0","method":"tools/list","id":1})
assert r.status_code == 401, f"Expected 401, got {r.status_code}"

print("All checks passed")
```

---

## Rollback Plan

This change is **additive** — it adds a new endpoint without modifying the existing one. Rollback is straightforward:

1. **If SSE breaks existing HTTP:** Revert the `create_app()` changes — remove the `Mount("/sse", ...)` route and the `sse_app` creation. The auth middleware change (accepting query params) is harmless and can stay.

2. **If auth middleware change breaks something:** Revert `AuthMiddleware.dispatch()` to the original version that only checks headers. This is a single-function revert.

3. **Full rollback:** Revert the entire commit. Since all changes are in one file ([`server.py`](server.py)), this is a single `git revert`.

4. **Image rollback:** In Coolify, change the image tag to the previous SHA: `ghcr.io/u2giants/devops-mcp:sha-<previous_commit>`. Or use `git revert` + push to `main` for a new build.

---

## Migration Notes

### What stays the same
- All existing client configurations (Claude, Gemini, ChatGPT, Codex) — no changes needed
- The `/mcp` endpoint URL and behavior
- Bearer token header auth
- All tools and their signatures
- Audit logging format and location
- Docker image, ports, volumes, env vars
- CI/CD pipeline

### What changes
- `AuthMiddleware` now also accepts `?token=` query parameter (backward compatible)
- New `/sse` mount point with SSE transport
- New documentation for Windsurf/Roo Code setup

### What's new
- SSE transport at `/sse/sse` (or `/stream/sse` — Builder to decide on mount point)
- Query-parameter auth support on all endpoints
- `docs/windsurf-roo-setup.md` documentation

---

## Open Questions for Builder

1. **Exact SSE mount path:** Test whether `Mount("/sse", app=sse_app)` results in `/sse/sse` as the SSE stream URL, or if FastMCP handles path prefixing differently. Adjust the mount point to produce the cleanest URL. Options:
   - Mount at `/sse` → URL is `/sse/sse` (functional but redundant)
   - Mount at `/stream` → URL is `/stream/sse` (cleaner)
   - Mount at `/` with SSE app configured with a path prefix → needs FastMCP API research

2. **FastMCP `http_app()` with `transport="sse"`:** Verify this is the correct API call. Check FastMCP docs/source for the exact parameter. It may be `sse_app = mcp.http_app(transport="sse")` or there may be a separate `mcp.sse_app()` method.

3. **Contextvar propagation in SSE:** SSE connections are long-lived. Verify that `current_agent` contextvar set during the initial SSE handshake request persists for subsequent tool calls on the same SSE session. If not, the auth middleware may need to set it on every `/messages` POST as well (which it should, since the middleware runs on all requests).

4. **Cloudflare Tunnel + SSE:** Verify that Cloudflare Tunnel supports SSE (long-lived HTTP connections with chunked transfer encoding). Cloudflare generally supports SSE, but the tunnel configuration may need `noTLSVerify` or timeout adjustments. Test with a real Windsurf connection.

# Architecture Decisions

## 2026-04-08: Windsurf/Roo MCP Compatibility — SSE Transport + Query-Param Auth

### Context

Windsurf's MCP client supports SSE transport via `serverUrl` but cannot send custom HTTP headers. The devops-mcp server only exposes stateless HTTP with `Authorization: Bearer <token>` header auth. Windsurf cannot connect.

### Decisions Made

#### 1. Dual-transport: SSE alongside HTTP (not replacing it)

**Decision:** Add SSE as a second transport at `/sse`, keep HTTP at `/mcp` unchanged.

**Alternatives considered:**
- Replace HTTP with SSE entirely → rejected because Claude/Gemini/ChatGPT/Codex all use HTTP transport and would break
- Use Streamable HTTP (new MCP spec) → rejected because Windsurf doesn't support it yet and FastMCP's support is via the existing `stateless_http` flag which is already in use
- stdio proxy → rejected because it requires a local process, defeating the purpose of a remote server

**Rationale:** Additive change with zero risk to existing clients. Both transports share the same FastMCP instance, tools, and audit middleware.

#### 2. Query-parameter token auth (not OAuth, not path-based)

**Decision:** Accept `?token=<secret>` as an alternative to `Authorization: Bearer <token>` header.

**Alternatives considered:**
- Path-based token (`/sse/<token>/sse`) → rejected because tokens in URL paths are more likely to be logged by reverse proxies and appear in server access logs; also makes routing messy
- OAuth 2.0 flow → rejected as massive overkill for a single-user devops server with 5 agents; adds complexity, new dependencies, and a token exchange flow that Windsurf may not support
- API key in a custom header → rejected because Windsurf can't send custom headers (the whole problem)
- Separate auth endpoint that returns a session cookie → rejected because Windsurf's SSE client doesn't support cookie-based auth flows

**Rationale:** Query params are the simplest mechanism that works with Windsurf's `serverUrl`-only config. The token travels over HTTPS (encrypted), and Cloudflare Tunnel adds another layer. Query params in URLs can appear in logs, but our stack (Cloudflare Tunnel → direct container, no Traefik) doesn't log URLs by default.

#### 3. Single AuthMiddleware handles both auth methods (not separate middleware per transport)

**Decision:** Modify the existing `AuthMiddleware` to check header first, then query param. One middleware, one code path.

**Alternatives considered:**
- Separate middleware for SSE routes that only checks query params → rejected because it duplicates auth logic and creates two places to maintain token validation
- Auth at the FastMCP layer instead of ASGI layer → rejected because the ASGI middleware approach is already proven and the contextvar bridge works

**Rationale:** DRY principle. The auth logic is identical regardless of where the token comes from. Header takes priority when both are present (defensive, but shouldn't happen in practice).

#### 4. No new dependencies

**Decision:** FastMCP >=2.14.0 already supports SSE transport natively. No new packages needed.

**Rationale:** Fewer dependencies = fewer things to break. The existing `fastmcp` package handles both HTTP and SSE wire protocols.

#### 5. No new environment variables or Docker changes

**Decision:** Existing `TOKEN_*` env vars work for both transports. Same port, same container config.

**Rationale:** Zero operational change for deployment. The only change is in `server.py` code.

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SSE mount breaks existing `/mcp` route | Low | High | Mount `/sse` before `/` in Starlette routes; test HTTP endpoint after deploy |
| Contextvar doesn't propagate in SSE sessions | Medium | High | Test audit logging with SSE tool calls; if broken, set contextvar on every POST to `/messages` |
| Cloudflare Tunnel drops SSE connections | Low | Medium | Cloudflare supports SSE; test with real Windsurf client; tunnel timeouts are configurable |
| Token in URL logged somewhere | Low | Low | HTTPS encrypts URL; no proxy logging in our stack; document the tradeoff |

### References

- [FastMCP SSE docs](https://gofastmcp.com)
- [Windsurf MCP config](https://docs.windsurf.com/windsurf/mcp)

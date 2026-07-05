# Server internals (server.py)

`server.py` is 620 lines. This document explains every section.

---

## Module-level configuration

```python
HOST_ROOT = os.environ.get("HOST_ROOT", "/host")
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/audit/mcp-audit.log")
MAX_OUTPUT = int(os.environ.get("MAX_OUTPUT_CHARS", "60000"))
DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", "120"))
```

All tuneable via environment variables. Defaults are appropriate for container
deployment. If running directly on host (outside Docker), set `HOST_ROOT=/` and
the server will skip the `/host` prefix.

---

## Token registry

```python
TOKENS: dict[str, str] = {}
for key, value in os.environ.items():
    if key.startswith("TOKEN_") and value:
        agent_name = key[6:].lower()
        TOKENS[value] = agent_name
```

Reads at startup only. **Adding a new token requires a container restart** — the
server does not hot-reload environment variables. The dict maps `token_string → agent_name`.

### Design choice: one token per client tool, not per AI model

Tokens are named after the *tool* using the server (e.g. `TOKEN_ROOCODE`), not the
underlying AI model (e.g. `TOKEN_GPT4`). This means the audit log shows `roocode`
did something regardless of whether Roo Code was using GPT-4 or Claude at the time.

---

## Tool registration

```python
_registered_tools: list[str] = []
_operation_tools: dict[str, dict[str, Any]] = {}

def _tool(fn):
    wrapped = mcp.tool(fn)
    _registered_tools.append(fn.__name__)
    return wrapped

def _operation(description: str):
    ...
```

Always-on MCP tools use `@_tool` instead of `@mcp.tool`. This is identical to
`@mcp.tool` except it also appends the function name to `_registered_tools`, which
the status page uses to list visible tools without calling async code at request
time.

The `FastMCP(..., instructions=MCP_INSTRUCTIONS, ...)` constructor gives clients
session-level guidance: browse/search/detail DevOps operations first, then call
`invoke_tool` with the exact returned operation name. Clients may incorporate this
hint into their system prompt during initialization.

Host operations use `@_operation(...)`. They are callable through `invoke_tool`,
but are not directly exposed in the MCP tool schema list. This keeps MCP clients
from loading every powerful DevOps operation into every chat. The intended flow is:

1. Call `list_capabilities(category?, safety?)` for orientation, or `tool_search(query)`.
2. Call `get_capability_details(name)` when exact args/examples are needed.
3. Call `invoke_tool(name, args)`.

**Do not use `@mcp.tool` directly** — the tool will work but won't appear on the
status page.

---

## Auth middleware (ASGI layer)

```python
PUBLIC_PATHS = {"/", "/status"}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        ...
```

Starlette `BaseHTTPMiddleware` applied at the HTTP level. Runs before FastMCP
processes the MCP protocol. Rejects requests with no/wrong token before they
reach the MCP layer.

`PUBLIC_PATHS` exempts the status page. If you add new public endpoints, add them
here. Everything else is gated.

---

## Audit middleware (FastMCP layer)

```python
class AuditMiddleware(McpMiddleware):
    async def on_call_tool(self, context, call_next):
        agent = current_agent.get()
        tool_name = context.message.name
        args = context.message.arguments
        start = time.time()
        try:
            result = await call_next(context)
            _audit(agent, tool_name, args, ok=True, ...)
            return result
        except Exception as exc:
            _audit(agent, tool_name, args, ok=False, error=str(exc), ...)
            raise
```

FastMCP's own middleware system, which intercepts at the MCP protocol level (after
HTTP parsing). `on_call_tool` is called for every tool invocation.

`current_agent.get()` reads the contextvar set by the ASGI auth middleware earlier
in the same request. See [architecture.md](architecture.md) for how these two layers
communicate.

---

## Host command execution

```python
IN_CONTAINER = os.path.isdir("/host/etc") and os.path.isfile("/.dockerenv")

NSENTER = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "--"]

def _run_on_host(command, cwd="/", timeout=DEFAULT_TIMEOUT, ...):
    cmd = (NSENTER if IN_CONTAINER else []) + ["bash", "-c", command]
    proc = subprocess.Popen(cmd, stdout=PIPE, stderr=PIPE, text=True,
                            start_new_session=True, ...)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)   # kill the WHOLE pgroup
        stdout, stderr = proc.communicate(timeout=5)
        ...
```

`IN_CONTAINER` is checked once at startup and cached. The detection logic:
- `/.dockerenv` exists inside every Docker container
- `/host/etc` exists when the host root is mounted at `/host`

Both must be true to activate nsenter mode. This means the server also works
directly on the host for development/testing (just run `HOST_ROOT=/ python server.py`).

### Process-group kill (do not simplify back to `subprocess.run`)

`subprocess.run(..., timeout=N)` only sends SIGKILL to the *direct* bash child.
For commands that fork — `ssh`, `docker`, any pipeline like `cmd1 | cmd2 | cmd3` —
bash exits but its grandchildren stay alive holding the stdout pipes open, so
`communicate()` blocks past the nominal timeout waiting for those pipes. MCP
clients then see this as a server hang, often surfacing as `-32001`.

The fix is `Popen(start_new_session=True)` (puts the child in its own process
group) plus `os.killpg(os.getpgid(proc.pid), SIGKILL)` on `TimeoutExpired`. The
whole group dies at once. Verified: `bash -c 'sleep 30 | sleep 30 | cat'` with
`timeout=2` returns at exactly 2.00s, not 30s.

This is the same root cause and fix as the synology-monitor 4-day runaway
`grep -R` incident — see [troubleshooting.md](troubleshooting.md) for the
production confirmation steps.

### Why nsenter and not just running commands in the container

The container has a minimal filesystem. It has no systemd, no apt, no nginx, no
application binaries. Running `systemctl restart nginx` in the container would fail
with "command not found". nsenter executes the command in the host's mount namespace,
where all the real binaries and services live.

### The `cwd` parameter

When IN_CONTAINER, the `cwd` parameter is passed as `NSENTER_CWD` in the environment
rather than as the subprocess working directory (which must be `/` for the nsenter
invocation itself). A future improvement would be to have the shell `cd` to the
desired directory inside the nsenter command.

---

## File operations

```python
def _host_path(path: str) -> str:
    if IN_CONTAINER:
        return f"{HOST_ROOT}{path}"
    return path
```

All file tools (`read_file`, `write_file`, `list_directory`) call `_host_path` to
translate logical paths to real paths. An AI calling `read_file("/etc/nginx/nginx.conf")`
gets `/host/etc/nginx/nginx.conf` transparently.

**Important:** write_file creates automatic `.bak` backups of existing files before
overwriting. Backups are timestamped: `filename.20260406-153200.bak`. These accumulate
over time and are not automatically cleaned up.

---

## Tools reference

### Always-on MCP tools

### `health()`
Returns server metadata: name, current agent identity, container mode, registered
agents, host root, audit log path, visible tools, and discoverable operations.
Useful as a first call to verify connectivity.

### `list_capabilities(category, safety, limit)`
Browses the hidden operation catalog without invoking anything. Returns compact
structured records with category, safety class, required/optional args, and an
example call. Optional filters avoid loading irrelevant catalog slices.

### `get_capability_details(name)`
Returns one operation's full contract, including example invocation, common
failures, and related tools. Use this before invoking an unfamiliar operation.

### `tool_search(query, limit)`
Searches the hidden operation registry by operation name and description. Returns
structured operation contracts and explicit `invoke_tool(...)` shapes. Use this
before calling `invoke_tool` unless you already know the exact operation name.

### `invoke_tool(name, args)`
Executes an operation discovered with `tool_search`. `args` must be a JSON object
matching the target operation parameters.

### Discoverable operations

### `run_command(command, cwd, timeout)`
The most powerful tool. Runs any bash command on the host via nsenter. No restrictions.
Output is capped at `MAX_OUTPUT_CHARS` (60,000 by default). Long-running commands
(> `timeout` seconds, default 120) are killed and return an error.

Use it for diagnostics and break-glass repair, not durable host configuration.
Packages, users, firewall, SSH/sudo, Docker engine or daemon config, systemd
units/timers, cron, `/etc`, `/usr/local/bin`, `/usr/local/sbin`, Cloudflare
Tunnel 1, Coolify host glue, and the backup/DNS watchdogs belong in
`/worksp/ansible` ([u2giants/ansible](https://github.com/u2giants/ansible)).
Break-glass direct repairs must be followed by an Ansible PR to capture or
reconcile drift; warn-mode reminders do not replace that PR/apply flow.

### `read_file(path, offset, limit, max_bytes)`
Returns line-numbered content. `offset` and `limit` are line numbers (not bytes).
Max `limit` is 10,000 lines per call.

Streams line-by-line — never loads the whole file. Stops as soon as the window
is filled OR `max_bytes` has been scanned (default 5 MB, hard cap 50 MB). For
files larger than `max_bytes` the response includes `truncated_by_bytes: true`
and `total_lines` is omitted. To read late content in a huge log, either:

- raise `max_bytes` (up to 50 MB), or
- shell out: `run_command("tail -n 1000 /path/to/log")` and parse the output.

Response fields: `size_bytes`, `scanned_lines`, `lines_returned`, `truncated`,
`truncated_by_bytes` (only when set), `total_lines` (only when EOF reached and
not byte-capped), `content`.

The previous implementation called `read_text().splitlines()` and allocated the
entire file before slicing — multi-GB logs would stall the worker thread for
seconds and risk OOM-killing the container.

### `write_file(path, content, make_backup)`
Writes the entire file content. Not a diff/patch — the full content must be provided.
Creates parent directories if needed. `make_backup=True` (default) saves the old file.

### `list_directory(path, recursive, max_entries)`
`recursive=True` can produce enormous output on `/` or `/home`. Always use with
`max_entries` and a specific path. Default `max_entries` is 200, hard cap 1000.

Streams from `rglob`/`iterdir` via `itertools.islice` and stops at `max_entries + 1`
entries (the +1 sets `truncated` correctly). The bounded window is then sorted —
NOT the full tree. The previous implementation called `sorted(p.rglob("*"))`,
which materialized every entry under the path before applying `max_entries`; on
`/host` that walked and held millions of paths in memory.

### `docker_ps(all_containers)`
Runs `docker ps` on the host. Returns formatted table output.

### `docker_logs(container, tail)`
Returns the last `tail` lines (default 100, max 5000) from a container.

### `docker_action(container, action)`
Allowed actions: `restart`, `stop`, `start`, `pause`, `unpause`, `rm`.
`rm` is dangerous — it deletes the container. Use with care.

### `service_status(service)`
If `service` is empty, lists all running systemd services.

### `service_action(service, action)`
Allowed actions: `start`, `stop`, `restart`, `enable`, `disable`, `reload`.

### `view_audit_log(lines)`
Returns the last N audit log entries (default 50, max 500) as structured JSON.
AIs can use this to see what has been done recently before making changes.

Uses `_tail_audit_lines()` which seeks to the **last 512 KB** of the audit
file rather than reading the whole thing. For audit logs larger than 512 KB
the `total` field is an estimate from the bytes-per-line average and the
response is marked `total_is_estimate: true`. This keeps both `view_audit_log`
and the status page O(1) as the log grows — the previous implementation
called `Path(AUDIT_LOG_PATH).read_text()` on every invocation.

---

## The status page

A Starlette `Route("/", status_page)` is added to the app before the FastMCP mount.
It reads `_registered_tools`, `_operation_tools`, and the last 30 audit log entries
(via `_tail_audit_lines`, which seeks to the last 512 KB of the file — not a full
read), renders them as HTML, and returns without auth.

The page auto-refreshes via `<meta http-equiv="refresh" content="30">`. No JavaScript.

---

## App assembly (`create_app`)

```python
def create_app() -> Starlette:
    asgi_middleware = [ASGIMiddleware(AuthMiddleware)] if TOKENS else []

    mcp_app = mcp.http_app(stateless_http=True, transport="http",
                            middleware=asgi_middleware)

    app = Starlette(
        routes=[
            Route("/", status_page),
            Route("/status", status_page),
            Mount("/", app=mcp_app),
        ],
        middleware=asgi_middleware,
    )
    return app
```

**The auth middleware is applied twice** — once to the outer Starlette app and once
to the inner FastMCP app. This is intentional: the outer middleware catches requests
to `/` and `/status` first (and passes them through because they're in `PUBLIC_PATHS`),
while the inner middleware guards the `/mcp` endpoint.

If `TOKENS` is empty (no `TOKEN_*` env vars set), auth middleware is not added at all
and the server is completely open. This will be logged as a warning at startup. Never
run in production without tokens.

---

## Running outside Docker (development)

```bash
pip install fastmcp uvicorn
TOKEN_CLAUDE=devtoken HOST_ROOT=/ AUDIT_LOG_PATH=/tmp/audit.log python server.py
```

In this mode `IN_CONTAINER` is `False`, commands run directly without nsenter, and
file paths are used as-is. Useful for testing changes before building the Docker image.

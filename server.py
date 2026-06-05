"""
DevOps MCP Server

A full-access MCP server for AI agents to perform devops and sysadmin tasks.
Authenticates callers via bearer tokens (one per agent) and logs every tool
call to an audit log with agent identity.

Designed to run inside a Docker container with host access via:
  - /var/run/docker.sock mounted
  - /host mounted to the host root filesystem
  - pid: host + privileged mode for nsenter
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import shlex
import signal
import subprocess
import time
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware as McpMiddleware, MiddlewareContext
from starlette.middleware import Middleware as ASGIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.applications import Starlette
from starlette.types import ASGIApp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST_ROOT = os.environ.get("HOST_ROOT", "/host")
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/audit/mcp-audit.log")
MAX_OUTPUT = int(os.environ.get("MAX_OUTPUT_CHARS", "60000"))
DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Token registry — reads every TOKEN_* env var at startup
# e.g. TOKEN_CLAUDE=abc123 => {"abc123": "claude"}
# ---------------------------------------------------------------------------

TOKENS: dict[str, str] = {}
for key, value in os.environ.items():
    if key.startswith("TOKEN_") and value:
        agent_name = key[6:].lower()  # TOKEN_CLAUDE -> claude
        TOKENS[value] = agent_name

if not TOKENS:
    logging.warning("No TOKEN_* environment variables set — server has no auth!")

# ---------------------------------------------------------------------------
# Context variable to carry agent identity from HTTP layer to MCP layer
# ---------------------------------------------------------------------------

current_agent: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_agent", default="unknown"
)

# ---------------------------------------------------------------------------
# Audit logger — writes one JSON line per tool call
# ---------------------------------------------------------------------------

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False

_audit_dir = os.path.dirname(AUDIT_LOG_PATH)
if _audit_dir:
    os.makedirs(_audit_dir, exist_ok=True)

_audit_handler = logging.FileHandler(AUDIT_LOG_PATH, encoding="utf-8")
_audit_handler.setFormatter(logging.Formatter("%(message)s"))
audit_logger.addHandler(_audit_handler)


def _audit(agent: str, tool: str, args: dict | None, ok: bool, duration_ms: int,
           error: str | None = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "tool": tool,
        "args": args or {},
        "ok": ok,
        "duration_ms": duration_ms,
    }
    if error:
        entry["error"] = error
    audit_logger.info(json.dumps(entry, default=str))


# ---------------------------------------------------------------------------
# ASGI auth middleware — checks Bearer token on every HTTP request
# ---------------------------------------------------------------------------

PUBLIC_PATHS = {"/", "/status"}
# SSE message POSTs are session-authenticated by the MCP transport itself
PUBLIC_PREFIXES = ("/sse/messages",)

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        token = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        elif request.query_params.get("token"):
            token = request.query_params.get("token")

        if token is None:
            return JSONResponse(
                {"error": "Missing auth: provide Authorization header or ?token= param"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="devops-mcp"'},
            )

        agent = TOKENS.get(token)
        if agent is None:
            return JSONResponse(
                {"error": "Invalid token"},
                status_code=403,
                headers={"WWW-Authenticate": 'Bearer realm="devops-mcp" error="invalid_token"'},
            )

        current_agent.set(agent)
        response = await call_next(request)
        return response


# ---------------------------------------------------------------------------
# MCP audit middleware — logs every tool call
# ---------------------------------------------------------------------------

class AuditMiddleware(McpMiddleware):
    async def on_call_tool(self, context, call_next):
        agent = current_agent.get()
        tool_name = context.message.name
        args = context.message.arguments
        start = time.time()
        try:
            result = await call_next(context)
            duration_ms = int((time.time() - start) * 1000)
            _audit(agent, tool_name, args, ok=True, duration_ms=duration_ms)
            return result
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            _audit(agent, tool_name, args, ok=False, duration_ms=duration_ms, error=str(exc))
            raise


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

MCP_INSTRUCTIONS = """
This DevOps MCP intentionally exposes only three always-on MCP tools:
health, tool_search, and invoke_tool.

For every host, Docker, systemd, file, or audit-log task, call tool_search first
to find the right hidden operation. Then call invoke_tool with the exact operation
name and an args object matching the operation description. Do not assume direct
tools such as run_command, docker_ps, read_file, or service_status are listed in
tools/list; they are discoverable operations to keep client context small.

Call health first when you need server context, visible tools, registered agents,
or the complete operation-name list. Treat write-capable operations with care:
this server has root-level host access, so prefer inspection commands before
state-changing commands.
""".strip()

mcp = FastMCP("devops-mcp", instructions=MCP_INSTRUCTIONS, middleware=[AuditMiddleware()])
_registered_tools: list[str] = []
_operation_tools: dict[str, dict[str, Any]] = {}


def _tool(fn):
    """Decorator: register with FastMCP and track name for the status page."""
    wrapped = mcp.tool(fn)
    _registered_tools.append(fn.__name__)
    return wrapped


def _operation(description: str):
    """Decorator: keep an operation callable through invoke_tool without exposing it directly."""
    def decorator(fn):
        _operation_tools[fn.__name__] = {
            "fn": fn,
            "description": description,
        }
        return fn

    return decorator

# ---------------------------------------------------------------------------
# Host command execution helpers
# ---------------------------------------------------------------------------

# When running inside Docker with pid:host and privileged, nsenter lets us
# execute commands in the host's namespaces — as if we were on the host itself.
NSENTER = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid", "--"]

# Detect if we're running inside Docker (with /host mounted) or directly on host
IN_CONTAINER = os.path.isdir("/host/etc") and os.path.isfile("/.dockerenv")


def _host_path(path: str) -> str:
    """Translate a logical host path to the actual filesystem path."""
    if IN_CONTAINER:
        return f"{HOST_ROOT}{path}"
    return path


def _run_on_host(
    command: str,
    cwd: str = "/",
    timeout: int = DEFAULT_TIMEOUT,
    max_output: int = MAX_OUTPUT,
) -> dict[str, Any]:
    """Run a shell command on the host via nsenter (container) or directly (host).

    Uses Popen + start_new_session so the child runs in its own process group.
    On timeout we SIGKILL the entire process group, not just the direct bash
    child. This is required for commands that fork — ssh, docker, pipelines —
    where bash exits while its grandchildren keep stdout pipes open. Without
    the process-group kill, subprocess.run can block well past `timeout`
    waiting for orphaned pipes to close, which surfaces in MCP clients as a
    "hang" on long-running ssh / read_file / docker calls.
    """
    timeout = max(1, min(timeout, 600))

    if IN_CONTAINER:
        cmd = NSENTER + ["bash", "-c", command]
        run_cwd = "/"
        env = {**os.environ, "NSENTER_CWD": cwd}
    else:
        cmd = ["bash", "-c", command]
        run_cwd = cwd
        env = None

    start = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=run_cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Failed to start process: {exc}"}

    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # SIGKILL the whole process group. os.getpgid uses the child's PID;
        # killpg with the negative PGID delivers the signal to every process
        # in that group, including grandchildren (ssh-agent, docker proxy,
        # pipeline stages) that bash spawned.
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        # Best-effort drain of whatever the killed process flushed.
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            stdout, stderr = "", ""

    stdout = stdout or ""
    stderr = stderr or ""
    duration = round(time.time() - start, 3)

    if timed_out:
        return {
            "ok": False,
            "error": f"Timed out after {timeout}s (process group killed via SIGKILL)",
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
            "duration_seconds": duration,
            "timed_out": True,
        }

    stdout_truncated = len(stdout) > max_output
    stderr_truncated = len(stderr) > max_output

    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout[:max_output],
        "stderr": stderr[:max_output],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "duration_seconds": duration,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@_tool
def health() -> dict[str, Any]:
    """Server health and configuration. Call this first to understand the server."""
    return {
        "server": "devops-mcp",
        "agent": current_agent.get(),
        "in_container": IN_CONTAINER,
        "registered_agents": list(TOKENS.values()),
        "host_root": HOST_ROOT if IN_CONTAINER else "/",
        "audit_log": AUDIT_LOG_PATH,
        "always_on_tools": sorted(_registered_tools),
        "available_operations": sorted(_operation_tools.keys()),
    }


@_tool
def tool_search(query: str, limit: int = 8) -> dict[str, Any]:
    """
    Search the hidden DevOps operation registry by keyword.
    Call this first for every host, Docker, file, service, or audit task. Then
    call invoke_tool with the exact returned operation name and an args object.
    """
    limit = max(1, min(limit, 30))
    terms = [term.lower() for term in query.split() if term.strip()]
    matches: list[dict[str, Any]] = []

    for name, spec in sorted(_operation_tools.items()):
        description = str(spec["description"])
        haystack = f"{name} {description}".lower()
        if not terms or all(term in haystack for term in terms):
            matches.append({
                "name": name,
                "description": description,
                "invoke": f'invoke_tool(name="{name}", args={{...}})',
            })

    return {
        "ok": True,
        "query": query,
        "count": len(matches[:limit]),
        "total_matches": len(matches),
        "operations": matches[:limit],
    }


@_tool
def invoke_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Execute a hidden DevOps operation discovered with tool_search.
    Pass the exact operation name and its arguments as a JSON object. If you do
    not know the exact name or arguments, call tool_search first.
    """
    spec = _operation_tools.get(name)
    if spec is None:
        return {
            "ok": False,
            "error": f"Unknown operation: {name}",
            "available_operations": sorted(_operation_tools.keys()),
        }
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be an object"}

    try:
        return spec["fn"](**args)
    except TypeError as exc:
        return {"ok": False, "error": f"Invalid arguments for {name}: {exc}"}


@_operation(
    "Run any shell command on the host. Use for apt, systemctl, docker, git, curl, or any CLI tool."
)
def run_command(
    command: str,
    cwd: str = "/",
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Run any shell command on the host. This has full root access.
    Use this for: apt, systemctl, docker, git, curl, or any CLI tool.
    The command runs in bash on the host system.
    """
    if not command.strip():
        return {"ok": False, "error": "command cannot be empty"}
    return _run_on_host(command, cwd=cwd, timeout=timeout)


@_operation(
    "Read a text file from the host filesystem with offset/limit pagination for large files."
)
def read_file(
    path: str,
    offset: int = 0,
    limit: int = 2000,
    max_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """
    Read a text file from the host filesystem.
    Returns line-numbered content. Use offset/limit for large files.

    Streams line-by-line and stops once the window is filled OR max_bytes is
    scanned. Does NOT load the whole file into memory (this used to hang on
    multi-GB logs). For files larger than max_bytes the response includes
    `truncated_by_bytes: true` and `total_lines` is omitted; use a higher
    `offset` or shell out via `run_command` with `tail`/`sed` for late content.

    Defaults: limit=2000 lines, max_bytes=5MB. Hard caps: limit≤10000,
    max_bytes≤50MB.
    """
    limit = max(1, min(limit, 10000))
    max_bytes = max(1, min(max_bytes, 50_000_000))
    offset = max(0, offset)
    try:
        real = _host_path(path)
        p = Path(real)
        if not p.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if not p.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}

        size = p.stat().st_size
        selected: list[str] = []
        scanned_lines = 0
        scanned_bytes = 0
        more_after_window = False
        truncated_by_bytes = False
        end = offset + limit

        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                scanned_lines = i + 1
                scanned_bytes += len(line.encode("utf-8", errors="replace"))
                if i >= end:
                    more_after_window = True
                    break
                if i >= offset:
                    selected.append(line.rstrip("\n"))
                if scanned_bytes >= max_bytes:
                    truncated_by_bytes = True
                    break

        numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(selected)]
        result: dict[str, Any] = {
            "ok": True,
            "path": path,
            "size_bytes": size,
            "offset": offset,
            "lines_returned": len(selected),
            "scanned_lines": scanned_lines,
            "truncated": more_after_window or truncated_by_bytes,
            "content": "\n".join(numbered),
        }
        if truncated_by_bytes:
            result["truncated_by_bytes"] = True
            result["max_bytes"] = max_bytes
        else:
            # We hit EOF or the end-of-window cleanly; scanned_lines is exact.
            result["total_lines"] = scanned_lines if not more_after_window else None
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": path}


@_operation(
    "Write a text file on the host filesystem, creating parent directories and optionally backing up existing files."
)
def write_file(path: str, content: str, make_backup: bool = True) -> dict[str, Any]:
    """
    Write a text file on the host filesystem. Creates parent directories if needed.
    If the file exists and make_backup is true, a timestamped .bak copy is saved first.
    """
    try:
        real = _host_path(path)
        p = Path(real)

        backup_path = ""
        if p.exists() and p.is_file() and make_backup:
            ts = time.strftime("%Y%m%d-%H%M%S")
            backup = p.with_name(f"{p.name}.{ts}.bak")
            import shutil
            shutil.copy2(p, backup)
            # Return the logical (non-/host) path for clarity
            backup_path = f"{path}.{ts}.bak"

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "path": path,
            "bytes_written": len(content.encode("utf-8")),
            "backup": backup_path,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": path}


@_operation(
    "List files and directories on the host filesystem. Recursive mode is bounded by max_entries."
)
def list_directory(path: str = "/", recursive: bool = False, max_entries: int = 200) -> dict[str, Any]:
    """
    List files and directories on the host filesystem.
    Use recursive=true carefully — can produce very large output.

    Streams from rglob/iterdir and stops at max_entries WITHOUT materializing
    the full tree. The previous version called sorted() over the entire
    iterator before applying max_entries, so a recursive list of /host walked
    and held millions of paths in memory before truncating — a server-side
    hang root cause on large directories.
    """
    max_entries = max(1, min(max_entries, 1000))
    try:
        real = _host_path(path)
        p = Path(real)
        if not p.exists():
            return {"ok": False, "error": f"Path not found: {path}"}
        if not p.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}

        # Take only the first max_entries + 1 entries — the +1 lets us report
        # whether there were more without walking the rest of the tree.
        raw_iter = p.rglob("*") if recursive else p.iterdir()
        try:
            window = list(islice(raw_iter, max_entries + 1))
        except OSError as exc:
            return {"ok": False, "error": f"Iteration failed: {exc}", "path": path}

        truncated = len(window) > max_entries
        window = window[:max_entries]

        items: list[dict[str, Any]] = []
        for entry in window:
            try:
                rel = entry.relative_to(real)
                logical = f"{path.rstrip('/')}/{rel}"
            except ValueError:
                logical = str(entry)
            item: dict[str, Any] = {
                "path": logical,
                "type": "dir" if entry.is_dir() else "file",
            }
            if entry.is_file():
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    pass
            items.append(item)

        # Sort only the bounded window — O(max_entries log max_entries), cheap.
        items.sort(key=lambda x: x["path"].lower())

        return {
            "ok": True,
            "path": path,
            "count": len(items),
            "truncated": truncated,
            "items": items,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": path}


@_operation("List Docker containers. Set all_containers=true to include stopped containers.")
def docker_ps(all_containers: bool = False) -> dict[str, Any]:
    """List Docker containers. Set all_containers=true to include stopped ones."""
    flag = "-a" if all_containers else ""
    return _run_on_host(
        f'docker ps {flag} --format "table {{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}\\t{{{{.Ports}}}}"'
    )


@_operation("Get recent logs from a Docker container.")
def docker_logs(container: str, tail: int = 100) -> dict[str, Any]:
    """Get logs from a Docker container."""
    tail = max(1, min(tail, 5000))
    safe = shlex.quote(container)
    return _run_on_host(f"docker logs --tail {tail} {safe}", timeout=30)


@_operation("Perform an action on a Docker container: restart, stop, start, pause, unpause, or rm.")
def docker_action(container: str, action: str = "restart") -> dict[str, Any]:
    """
    Perform an action on a Docker container.
    Actions: restart, stop, start, pause, unpause, rm (dangerous)
    """
    allowed = {"restart", "stop", "start", "pause", "unpause", "rm"}
    if action not in allowed:
        return {"ok": False, "error": f"Action must be one of: {sorted(allowed)}"}
    safe = shlex.quote(container)
    return _run_on_host(f"docker {action} {safe}", timeout=60)


@_operation("Check systemd service status, or list running services when service is empty.")
def service_status(service: str = "") -> dict[str, Any]:
    """
    Check systemd service status. If service is empty, lists all running services.
    """
    if not service:
        return _run_on_host(
            "systemctl list-units --type=service --state=running --no-pager",
            timeout=30,
        )
    safe = shlex.quote(service)
    return _run_on_host(f"systemctl status {safe} --no-pager", timeout=30)


@_operation("Manage a systemd service: start, stop, restart, enable, disable, or reload.")
def service_action(service: str, action: str = "restart") -> dict[str, Any]:
    """
    Manage a systemd service. Actions: start, stop, restart, enable, disable, reload
    """
    allowed = {"start", "stop", "restart", "enable", "disable", "reload"}
    if action not in allowed:
        return {"ok": False, "error": f"Action must be one of: {sorted(allowed)}"}
    safe = shlex.quote(service)
    return _run_on_host(f"systemctl {action} {safe}", timeout=60)


def _tail_audit_lines(n: int) -> tuple[list[str], int, bool]:
    """Read the last `n` lines of the audit log without loading the whole file.

    Returns (lines, total_estimate, exact_total). On small files we read everything
    and `exact_total` is True. On large files we seek to the last ~512KB and
    estimate total from bytes/line average.
    """
    p = Path(AUDIT_LOG_PATH)
    if not p.exists():
        return [], 0, True

    size = p.stat().st_size
    # 512KB is plenty for the last 500 audit entries (~1KB/line typical).
    tail_window = min(size, 512 * 1024)
    with p.open("rb") as fh:
        if tail_window < size:
            fh.seek(size - tail_window)
        data = fh.read(tail_window)

    # If we didn't start at the file head, drop the partial first line.
    exact_total = tail_window == size
    if not exact_total and b"\n" in data:
        data = data.split(b"\n", 1)[1]

    text = data.decode("utf-8", errors="replace")
    window_lines = text.strip().splitlines()

    if exact_total:
        total = len(window_lines)
    elif window_lines:
        avg_bytes = tail_window / max(1, len(window_lines))
        total = max(len(window_lines), int(size / max(1.0, avg_bytes)))
    else:
        total = 0

    return window_lines[-n:], total, exact_total


@_operation("View recent entries from the MCP audit log.")
def view_audit_log(lines: int = 50) -> dict[str, Any]:
    """View recent entries from the MCP audit log. Shows who did what and when.

    Reads only the tail of the log file, not the whole thing. For audit logs
    larger than ~512KB the `total` field is an estimate, marked
    `total_is_estimate: true`.
    """
    lines = max(1, min(lines, 500))
    try:
        recent, total, exact = _tail_audit_lines(lines)
        if not recent:
            return {"ok": True, "entries": [], "count": 0, "total": total, "message": "No audit log yet" if total == 0 else "Empty tail window"}
        entries = []
        for line in recent:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"raw": line})
        result: dict[str, Any] = {
            "ok": True,
            "count": len(entries),
            "total": total,
            "entries": entries,
        }
        if not exact:
            result["total_is_estimate"] = True
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Status page
# ---------------------------------------------------------------------------

def _read_recent_audit(n: int = 30) -> list[dict]:
    """Status-page helper. Tail-from-end so refreshes don't get slower as the log grows."""
    try:
        recent, _, _ = _tail_audit_lines(n)
        entries: list[dict] = []
        for line in reversed(recent):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries
    except Exception:
        return []


async def status_page(request: Request) -> HTMLResponse:
    entries = _read_recent_audit(30)
    agents = sorted(TOKENS.values())
    tools = sorted(_registered_tools)

    rows = ""
    for e in entries:
        ts = e.get("ts", "")
        time_str = ts[11:19] if len(ts) >= 19 else ts
        agent = e.get("agent", "?")
        tool = e.get("tool", "?")
        args = e.get("args", {})
        # Show the most meaningful arg: invoked operation, command, container, service, path
        detail = (
            args.get("name")
            or args.get("command")
            or args.get("container")
            or args.get("service")
            or args.get("path")
            or (", ".join(f"{k}={v}" for k, v in args.items()) if args else "")
        )
        if len(detail) > 60:
            detail = detail[:57] + "…"
        ok = e.get("ok", True)
        status_icon = "✓" if ok else "✗"
        status_class = "ok" if ok else "fail"
        ms = e.get("duration_ms", "")
        rows += f"""
        <tr>
          <td class="ts">{time_str}</td>
          <td class="agent">{agent}</td>
          <td class="tool">{tool}</td>
          <td class="detail">{detail}</td>
          <td class="{status_class}">{status_icon}</td>
          <td class="ms">{ms}ms</td>
        </tr>"""

    agent_pills = "".join(f'<span class="pill">{a}</span>' for a in agents)
    tool_list = "".join(f'<li>{t}</li>' for t in tools)
    operation_list = "".join(f'<li>{t}</li>' for t in sorted(_operation_tools.keys()))
    total_calls = len(entries)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>DevOps MCP — Status</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0f1117; color: #e2e8f0; min-height: 100vh; padding: 2rem; }}
    h1 {{ font-size: 1.4rem; font-weight: 600; color: #f8fafc; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #64748b; font-size: 0.85rem; margin-bottom: 2rem; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    .card {{ background: #1e2130; border: 1px solid #2d3148; border-radius: 10px; padding: 1.25rem; }}
    .card h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em;
                color: #64748b; margin-bottom: 0.75rem; }}
    .pill {{ display: inline-block; background: #2d3148; color: #a5b4fc;
             border-radius: 999px; padding: 0.2rem 0.7rem; font-size: 0.8rem;
             margin: 0.2rem; font-weight: 500; }}
    ul {{ list-style: none; }}
    ul li {{ color: #94a3b8; font-size: 0.85rem; padding: 0.15rem 0;
             border-bottom: 1px solid #1e2130; }}
    ul li::before {{ content: "⚙ "; color: #4f6ef7; }}
    .status-dot {{ width: 8px; height: 8px; border-radius: 50%;
                   background: #22c55e; display: inline-block; margin-right: 6px;
                   box-shadow: 0 0 6px #22c55e; animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.5; }} }}
    .log-card {{ background: #1e2130; border: 1px solid #2d3148; border-radius: 10px;
                 padding: 1.25rem; overflow-x: auto; }}
    .log-card h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: .08em;
                    color: #64748b; margin-bottom: 0.75rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
    th {{ text-align: left; color: #475569; font-weight: 500; padding: 0.4rem 0.6rem;
          border-bottom: 1px solid #2d3148; font-size: 0.75rem; text-transform: uppercase; }}
    td {{ padding: 0.45rem 0.6rem; border-bottom: 1px solid #1a1f2e; vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #252840; }}
    .ts {{ color: #475569; font-family: monospace; white-space: nowrap; }}
    .agent {{ color: #a5b4fc; font-weight: 500; }}
    .tool {{ color: #7dd3fc; font-family: monospace; }}
    .detail {{ color: #94a3b8; font-family: monospace; }}
    .ok {{ color: #22c55e; text-align: center; }}
    .fail {{ color: #f87171; text-align: center; }}
    .ms {{ color: #475569; text-align: right; font-size: 0.75rem; }}
    .empty {{ color: #475569; font-style: italic; padding: 1rem 0; }}
    .refresh {{ color: #475569; font-size: 0.75rem; margin-top: 1.5rem; text-align: right; }}
  </style>
</head>
<body>
  <h1><span class="status-dot"></span>DevOps MCP Server</h1>
    <p class="subtitle">mcp.designflow.app &nbsp;·&nbsp; Streamable HTTP: /mcp &nbsp;·&nbsp; refreshes every 30s</p>

  <div class="grid">
    <div class="card">
      <h2>Connected Agents</h2>
      {agent_pills if agent_pills else '<span style="color:#475569">None configured</span>'}
    </div>
    <div class="card">
      <h2>Always-on MCP Tools</h2>
      <ul>{tool_list}</ul>
      <h2 style="margin-top:1rem">Discoverable Operations</h2>
      <p style="color:#64748b;font-size:.78rem;margin-bottom:.5rem">Use <code>tool_search</code>, then <code>invoke_tool</code>.</p>
      <ul>{operation_list}</ul>
    </div>
  </div>

  <div class="log-card">
    <h2>Recent Activity &nbsp;<span style="color:#475569;font-weight:400">last {total_calls} shown</span></h2>
    {"<table><thead><tr><th>Time</th><th>Agent</th><th>Tool</th><th>Detail</th><th></th><th>ms</th></tr></thead><tbody>" + rows + "</tbody></table>" if entries else '<p class="empty">No activity recorded yet.</p>'}
  </div>

  <p class="refresh">Auto-refreshes every 30 seconds</p>
</body>
</html>"""
    return HTMLResponse(html)


def create_app() -> Starlette:
    """Create the Starlette ASGI app with status page and auth middleware."""
    asgi_middleware = []
    if TOKENS:
        asgi_middleware.append(ASGIMiddleware(AuthMiddleware))

    # StreamableHTTP transport — for Claude Code CLI and modern MCP clients
    mcp_app = mcp.http_app(
        stateless_http=True,
        transport="http",
        middleware=asgi_middleware,
    )

    # SSE transport — for Roo Code / Cline and older MCP clients
    sse_app = mcp.http_app(transport="sse", middleware=asgi_middleware)

    app = Starlette(
        routes=[
            Route("/", status_page),
            Route("/status", status_page),
            Mount("/sse", app=sse_app),
            Mount("/", app=mcp_app),
        ],
        middleware=asgi_middleware,
        lifespan=mcp_app.lifespan,
    )
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("BIND_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")


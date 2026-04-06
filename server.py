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
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware as McpMiddleware, MiddlewareContext
from starlette.middleware import Middleware as ASGIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

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

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "Missing Authorization: Bearer <token>"}, status_code=401)
        token = auth[7:]
        agent = TOKENS.get(token)
        if agent is None:
            return JSONResponse({"error": "Invalid token"}, status_code=403)
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

mcp = FastMCP("devops-mcp", middleware=[AuditMiddleware()])

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
    """Run a shell command on the host via nsenter (container) or directly (host)."""
    timeout = max(1, min(timeout, 600))

    if IN_CONTAINER:
        cmd = NSENTER + ["bash", "-c", command]
        run_cwd = "/"
    else:
        cmd = ["bash", "-c", command]
        run_cwd = cwd

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=run_cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "NSENTER_CWD": cwd} if IN_CONTAINER else None,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": f"Timed out after {timeout}s",
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": (exc.stderr or "")[-4000:],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    stdout_truncated = len(stdout) > max_output
    stderr_truncated = len(stderr) > max_output

    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout[:max_output],
        "stderr": stderr[:max_output],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "duration_seconds": round(time.time() - start, 3),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool
def health() -> dict[str, Any]:
    """Server health and configuration. Call this first to understand the server."""
    return {
        "server": "devops-mcp",
        "agent": current_agent.get(),
        "in_container": IN_CONTAINER,
        "registered_agents": list(TOKENS.values()),
        "host_root": HOST_ROOT if IN_CONTAINER else "/",
        "audit_log": AUDIT_LOG_PATH,
    }


@mcp.tool
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


@mcp.tool
def read_file(path: str, offset: int = 0, limit: int = 2000) -> dict[str, Any]:
    """
    Read a text file from the host filesystem.
    Returns line-numbered content. Use offset/limit for large files.
    """
    limit = max(1, min(limit, 10000))
    try:
        real = _host_path(path)
        p = Path(real)
        if not p.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if not p.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        selected = lines[offset:offset + limit]
        numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(selected)]
        return {
            "ok": True,
            "path": path,
            "total_lines": total,
            "offset": offset,
            "lines_returned": len(selected),
            "truncated": (offset + limit) < total,
            "content": "\n".join(numbered),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": path}


@mcp.tool
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


@mcp.tool
def list_directory(path: str = "/", recursive: bool = False, max_entries: int = 200) -> dict[str, Any]:
    """
    List files and directories on the host filesystem.
    Use recursive=true carefully — can produce very large output.
    """
    max_entries = max(1, min(max_entries, 1000))
    try:
        real = _host_path(path)
        p = Path(real)
        if not p.exists():
            return {"ok": False, "error": f"Path not found: {path}"}
        if not p.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}

        iterator = p.rglob("*") if recursive else p.iterdir()
        items = []
        for entry in sorted(iterator, key=lambda e: str(e).lower()):
            # Convert back to logical host path
            try:
                rel = entry.relative_to(real)
                logical = f"{path.rstrip('/')}/{rel}"
            except ValueError:
                logical = str(entry)

            item = {
                "path": logical,
                "type": "dir" if entry.is_dir() else "file",
            }
            if entry.is_file():
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    pass
            items.append(item)
            if len(items) >= max_entries:
                break

        return {
            "ok": True,
            "path": path,
            "count": len(items),
            "truncated": len(items) >= max_entries,
            "items": items,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": path}


@mcp.tool
def docker_ps(all_containers: bool = False) -> dict[str, Any]:
    """List Docker containers. Set all_containers=true to include stopped ones."""
    flag = "-a" if all_containers else ""
    return _run_on_host(
        f'docker ps {flag} --format "table {{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}\\t{{{{.Ports}}}}"'
    )


@mcp.tool
def docker_logs(container: str, tail: int = 100) -> dict[str, Any]:
    """Get logs from a Docker container."""
    tail = max(1, min(tail, 5000))
    safe = shlex.quote(container)
    return _run_on_host(f"docker logs --tail {tail} {safe}", timeout=30)


@mcp.tool
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


@mcp.tool
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


@mcp.tool
def service_action(service: str, action: str = "restart") -> dict[str, Any]:
    """
    Manage a systemd service. Actions: start, stop, restart, enable, disable, reload
    """
    allowed = {"start", "stop", "restart", "enable", "disable", "reload"}
    if action not in allowed:
        return {"ok": False, "error": f"Action must be one of: {sorted(allowed)}"}
    safe = shlex.quote(service)
    return _run_on_host(f"systemctl {action} {safe}", timeout=60)


@mcp.tool
def view_audit_log(lines: int = 50) -> dict[str, Any]:
    """View recent entries from the MCP audit log. Shows who did what and when."""
    lines = max(1, min(lines, 500))
    try:
        p = Path(AUDIT_LOG_PATH)
        if not p.exists():
            return {"ok": True, "entries": [], "message": "No audit log yet"}
        all_lines = p.read_text(encoding="utf-8").strip().splitlines()
        recent = all_lines[-lines:]
        entries = []
        for line in recent:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"raw": line})
        return {"ok": True, "count": len(entries), "total": len(all_lines), "entries": entries}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# App entrypoint
# ---------------------------------------------------------------------------

def create_app():
    """Create the Starlette ASGI app with auth middleware."""
    asgi_middleware = []
    if TOKENS:
        asgi_middleware.append(ASGIMiddleware(AuthMiddleware))

    return mcp.http_app(
        stateless_http=True,
        transport="http",
        middleware=asgi_middleware,
    )


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("BIND_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")

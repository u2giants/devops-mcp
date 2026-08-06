import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import server


def context(name, arguments):
    return SimpleNamespace(message=SimpleNamespace(name=name, arguments=arguments))


@pytest.mark.anyio
async def test_concurrent_agent_identities_do_not_cross_audit_contexts():
    middleware = server.AuditMiddleware()
    entries = []

    async def one(agent, delay):
        token = server.current_agent.set(agent)
        try:
            async def call_next(_context):
                await asyncio.sleep(delay)
                return {"ok": True}

            await middleware.on_call_tool(context("health", {}), call_next)
        finally:
            server.current_agent.reset(token)

    def capture(agent, tool, args, ok, duration_ms, error=None):
        entries.append({"agent": agent, "tool": tool, "ok": ok})

    with patch.object(server, "_audit", side_effect=capture):
        await asyncio.gather(one("agent-a", 0.02), one("agent-b", 0))

    assert sorted(entry["agent"] for entry in entries) == ["agent-a", "agent-b"]
    assert all(entry["tool"] == "health" and entry["ok"] for entry in entries)


@pytest.mark.anyio
async def test_audit_failure_is_recorded_and_reraised():
    middleware = server.AuditMiddleware()

    async def fails(_context):
        raise ValueError("synthetic")

    with patch.object(server, "_audit") as audit:
        with pytest.raises(ValueError, match="synthetic"):
            await middleware.on_call_tool(context("health", {}), fails)
    assert audit.call_args.kwargs["ok"] is False
    assert audit.call_args.kwargs["error"] == "synthetic"


def test_audit_entry_is_structured_json_without_cross_request_state():
    messages = []
    with patch.object(server.audit_logger, "info", side_effect=messages.append):
        server._audit("agent-a", "health", {"safe": True}, True, 2)
    assert json.loads(messages[0]) == {
        "ts": json.loads(messages[0])["ts"],
        "agent": "agent-a",
        "tool": "health",
        "args": {"safe": True},
        "ok": True,
        "duration_ms": 2,
    }


def test_transport_access_log_excludes_all_request_secrets():
    async def ok(_request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/sse/messages/private-segment", ok, methods=["POST"])],
        middleware=[Middleware(server.TransportAccessMiddleware)],
    )
    messages = []
    with patch.object(server.transport_access_logger, "info", side_effect=messages.append):
        response = TestClient(app).post(
            "/sse/messages/private-segment?token=query-secret",
            headers={"Authorization": "Bearer header-secret"},
            json={"argument": "body-secret"},
        )

    assert response.status_code == 200
    entry = json.loads(messages[0])
    assert entry == {
        "ts": entry["ts"],
        "event": "transport_access",
        "method": "POST",
        "route": "/sse/messages",
        "status": 200,
    }
    assert all(
        secret not in messages[0]
        for secret in ("query-secret", "header-secret", "body-secret", "private-segment")
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "/"),
        ("/status/details", "/status"),
        ("/mcp/session-id", "/mcp"),
        ("/sse/sse", "/sse"),
        ("/sse/messages/session-id", "/sse/messages"),
        ("/token-in-path", "/other"),
    ],
)
def test_transport_route_normalization(path, expected):
    assert server._normalized_transport_route(path) == expected

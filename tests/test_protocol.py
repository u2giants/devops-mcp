import hashlib
import json
from pathlib import Path

import pytest
from fastmcp import Client

import server


FIXTURE = Path(__file__).parent / "fixtures" / "protocol-conformance-contract.json"
VISIBLE_TOOLS = [
    "health",
    "list_capabilities",
    "get_capability_details",
    "tool_search",
    "invoke_tool",
]


def test_protocol_contract_has_all_stable_cases_and_valid_digest():
    contract = json.loads(FIXTURE.read_text())
    ids = [case["id"] for case in contract["cases"]]
    assert contract["contractVersion"] == "1.0.0"
    assert contract["wireRevision"] == "2026-07-28"
    assert len(ids) == len(set(ids)) == 21

    digest_input = {
        "contractVersion": contract["contractVersion"],
        "wireRevision": contract["wireRevision"],
        "cases": contract["cases"],
    }
    actual = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert actual == contract["expectedDigest"]


@pytest.mark.anyio
async def test_visible_tool_surface_is_small_and_deterministic():
    async with Client(server.mcp) as client:
        first = await client.list_tools()
        second = await client.list_tools()

    assert [tool.name for tool in first] == VISIBLE_TOOLS
    assert [tool.name for tool in second] == VISIBLE_TOOLS


def test_import_does_not_create_audit_handler_or_application():
    assert server._audit_handler is None
    assert not hasattr(server, "app")


def test_production_startup_fails_closed_without_tokens():
    with pytest.raises(RuntimeError, match=r"TOKEN_\*"):
        server.create_app(server.ServerConfig(tokens={}, audit_log_path=None))


def test_explicit_test_mode_allows_auth_free_in_process_app():
    app = server.create_app(
        server.ServerConfig(tokens={}, audit_log_path=None, test_mode=True)
    )
    assert app is not None

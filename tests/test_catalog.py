import inspect

import server


def test_catalog_and_search_order_are_deterministic():
    first = server.list_capabilities()
    second = server.list_capabilities()
    assert first == second
    assert [item["name"] for item in first["capabilities"]] == sorted(
        server._operation_tools
    )
    assert server.tool_search("") == server.tool_search("")


def test_hidden_operation_contracts_match_signatures():
    for name, spec in server._operation_tools.items():
        contract = server.get_capability_details(name)["capability"]
        signature = inspect.signature(spec["fn"])
        expected_required = {
            parameter_name
            for parameter_name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
        }
        expected_optional = set(signature.parameters) - expected_required
        assert {item["name"] for item in contract["required_args"]} == expected_required
        assert {item["name"] for item in contract["optional_args"]} == expected_optional


def test_safety_metadata_is_explicit_and_never_falls_back_to_read_only():
    for name, spec in server._operation_tools.items():
        safety = server._operation_safety(name, spec["description"])
        assert safety["classification"] in {
            "read_only", "state_changing", "destructive"
        }
    unknown = server._operation_safety("future_operation", "ambiguous work")
    assert unknown["classification"] == "unknown"
    assert unknown["read_only"] is False
    assert unknown["requires_confirmation"] is True


def test_invalid_hidden_arguments_never_execute():
    result = server.invoke_tool("run_command", {})
    assert result["ok"] is False
    assert "Invalid arguments" in result["error"]

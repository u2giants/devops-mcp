from unittest.mock import Mock, patch

import server


def test_invoke_tool_cannot_raise_command_timeout_above_policy():
    with patch.object(server, "_run_on_host", return_value={"ok": True}) as run:
        result = server.invoke_tool(
            "run_command", {"command": "harmless", "timeout": 10_000}
        )
    assert result["ok"] is True
    # run_command passes caller input to the single enforcement point.
    assert run.call_args.kwargs["timeout"] == 10_000


def test_current_command_policy_clamps_at_600_seconds_until_step_9b():
    process = Mock(pid=1234, returncode=0)
    process.communicate.return_value = ("ok", "")
    with patch.object(server.subprocess, "Popen", return_value=process) as popen:
        result = server._run_on_host("harmless", timeout=10_000)
    assert result["ok"] is True
    process.communicate.assert_called_once_with(timeout=600)
    popen.assert_called_once()

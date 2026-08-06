import subprocess
from unittest.mock import Mock, patch

import server


def test_timeout_kills_entire_process_group_and_returns_error_shape():
    process = Mock(pid=4242, returncode=-9)
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("fake", 600),
        ("partial-out", "partial-err"),
    ]
    with (
        patch.object(server.subprocess, "Popen", return_value=process) as popen,
        patch.object(server.os, "getpgid", return_value=4242),
        patch.object(server.os, "killpg") as killpg,
    ):
        result = server._run_on_host("never executed", timeout=999)

    assert popen.call_args.kwargs["start_new_session"] is True
    assert process.communicate.call_args_list[0].kwargs["timeout"] == 600
    killpg.assert_called_once_with(4242, server.signal.SIGKILL)
    assert result["ok"] is False
    assert result["timed_out"] is True
    assert "600s" in result["error"]


def test_process_start_failure_is_loud():
    with patch.object(server.subprocess, "Popen", side_effect=OSError("blocked")):
        result = server._run_on_host("never executed")
    assert result == {"ok": False, "error": "Failed to start process: blocked"}

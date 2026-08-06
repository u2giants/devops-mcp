import json

import server


def test_read_file_honors_line_bound(tmp_path, monkeypatch):
    path = tmp_path / "many.txt"
    path.write_text("".join(f"line-{i}\n" for i in range(50)))
    monkeypatch.setattr(server, "IN_CONTAINER", False)
    result = server.read_file(str(path), offset=3, limit=4, max_bytes=10_000)
    assert result["lines_returned"] == 4
    assert result["scanned_lines"] <= 8
    assert result["truncated"] is True


def test_read_file_honors_byte_bound(tmp_path, monkeypatch):
    path = tmp_path / "wide.txt"
    path.write_text("x" * 100 + "\n" + "unseen\n")
    monkeypatch.setattr(server, "IN_CONTAINER", False)
    result = server.read_file(str(path), limit=100, max_bytes=25)
    assert result["truncated_by_bytes"] is True
    assert result["scanned_lines"] == 1


def test_recursive_list_stops_after_bounded_window(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    root.mkdir()
    for index in range(20):
        (root / f"{index:02}.txt").write_text("x")
    monkeypatch.setattr(server, "IN_CONTAINER", False)
    result = server.list_directory(str(root), recursive=True, max_entries=3)
    assert result["count"] == 3
    assert result["truncated"] is True


def test_audit_reader_seeks_only_tail_window(tmp_path, monkeypatch):
    path = tmp_path / "audit.log"
    line = json.dumps({"ok": True}) + "\n"
    path.write_text(line * 60_000)
    monkeypatch.setattr(server, "AUDIT_LOG_PATH", str(path))
    recent, _, exact = server._tail_audit_lines(1)
    assert recent == [line.strip()]
    assert exact is False

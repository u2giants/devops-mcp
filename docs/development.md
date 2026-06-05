# Development

## Local prerequisites

- Python 3.12+
- Docker, if testing the container image
- GitHub CLI, if inspecting workflow runs

Install dependencies:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run locally

For syntax/import checks:

```sh
python -m py_compile server.py
```

To start the server without container host mounts:

```sh
TOKEN_CODEX=devtoken HOST_ROOT=/ AUDIT_LOG_PATH=/tmp/devops-mcp-audit.log python server.py
```

PowerShell:

```powershell
$env:TOKEN_CODEX="devtoken"
$env:HOST_ROOT="/"
$env:AUDIT_LOG_PATH="$env:TEMP\devops-mcp-audit.log"
python server.py
```

Local host-control behavior is limited unless the process runs in the production
container shape (`privileged`, `pid: host`, `/host` mount, Docker socket mount).
Use local runs for protocol/tool-shape tests, not as proof that `nsenter` host
commands work.

## Useful checks

Compile:

```sh
python -m py_compile server.py
```

Import and inspect the small tool surface:

```sh
python - <<'PY'
import server
print(server.health()["always_on_tools"])
print(server.tool_search("docker")["operations"][0])
PY
```

Container build:

```sh
docker build -t devops-mcp:local .
```

## MCP development rules

- Keep `tools/list` small: only `health`, `tool_search`, and `invoke_tool` should
  be always-on unless there is a strong reason.
- Add host/Docker/systemd/file/audit capabilities as hidden `@_operation`s.
- Give every operation a clear description; `tool_search` exposes that text to
  AI clients.
- Keep process and file reads bounded. Do not add unbounded recursive filesystem
  walks or full-log reads.
- Do not commit token values, audit logs, or local `.env` files.

## Debugging production

Use the MCP status page, Coolify logs, or audited MCP operations. SSH and manual
server edits are not normal development or deployment paths.

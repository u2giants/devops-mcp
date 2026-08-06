# Development

## Local prerequisites

- Python 3.12
- uv 0.11.2
- Docker, if testing the container image
- GitHub CLI, if inspecting workflow runs

Install dependencies:

```sh
uv sync --locked
```

On Windows PowerShell:

```powershell
uv sync --locked
```

## Run locally

For syntax/import checks:

```sh
uv run python -m py_compile server.py dependency_versions.py
```

To start the server without container host mounts:

```sh
TOKEN_CODEX=devtoken HOST_ROOT=/ AUDIT_LOG_PATH=/tmp/devops-mcp-audit.log uv run python server.py
```

PowerShell:

```powershell
$env:TOKEN_CODEX="devtoken"
$env:HOST_ROOT="/"
$env:AUDIT_LOG_PATH="$env:TEMP\devops-mcp-audit.log"
uv run python server.py
```

Local host-control behavior is limited unless the process runs in the production
container shape (`privileged`, `pid: host`, `/host` mount, Docker socket mount).
Use local runs for protocol/tool-shape tests, not as proof that `nsenter` host
commands work.

## Useful checks

Compile:

```sh
uv run python -m py_compile server.py dependency_versions.py

Report the exact runtime framework versions used by health metadata and CI:

```sh
uv run python dependency_versions.py
```

Run the baseline tests:

```sh
AUDIT_LOG_PATH=/tmp/devops-mcp-audit.log uv run python -m unittest discover -v
```

Import and inspect the small tool surface:

```sh
uv run python - <<'PY'
import server
print(server.health()["always_on_tools"])
print(server.list_capabilities(category="docker", limit=1)["capabilities"][0])
print(server.tool_search("docker")["operations"][0]["example_call"])
PY
```

Container build:

```sh
docker build -t devops-mcp:local .
```

## Dependency upgrades

Dependency versions are declared in `pyproject.toml` and every transitive version
is committed in `uv.lock`. Normal installs, CI, and Docker builds use the lock and
must never fall back to `pip install`, an unlocked `uv sync`, or `uv lock` during
a build.

For an intentional upgrade:

1. Read the package changelog, including FastMCP and MCP protocol/transport changes.
2. Change the exact version in `pyproject.toml`.
3. Run `uv lock --upgrade-package <package>` and review the complete `uv.lock` diff.
4. Run `uv sync --locked`.
5. Run `uv run python dependency_versions.py` and confirm the intended versions.
6. Run `uv run python -m unittest discover -v` and the protocol suite once it is added.
7. Run `docker build --no-cache -t devops-mcp:lock-check .` before committing.

If `pyproject.toml` changes without a matching lock refresh, `uv sync --locked`
and the Docker build must fail. That failure is a safety gate, not an error to
bypass.

## MCP development rules

- Keep `tools/list` small: only `health`, `list_capabilities`,
  `get_capability_details`, `tool_search`, and `invoke_tool` should be always-on
  unless there is a strong reason.
- Add host/Docker/systemd/file/audit capabilities as hidden `@_operation`s.
- Give every operation a clear description; catalog/search/detail tools expose
  that text and derived args/safety metadata to AI clients only when requested.
- Keep process and file reads bounded. Do not add unbounded recursive filesystem
  walks or full-log reads.
- Do not commit token values, audit logs, or local `.env` files.

## Debugging production

Use the MCP status page, Coolify logs, or audited MCP operations. SSH and manual
server edits are not normal development or deployment paths.

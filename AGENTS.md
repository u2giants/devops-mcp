# AGENTS.md — DevOps MCP Developer Guide

Read this first. It is the canonical operating guide for developers and AI coding
sessions working in this repo.

## 1. Project summary

`devops-mcp` is a privileged MCP server that lets approved AI clients perform
DevOps and sysadmin work on the production VPS through audited tools. It runs as a
Coolify-managed Docker service behind Cloudflare Tunnel, authenticates each client
with a per-agent bearer token, exposes a small FastMCP tool surface, and executes
host commands through `nsenter`, `/host`, and the Docker socket. The outcome that
matters is controlled, logged root-equivalent VPS access without ad hoc SSH edits.

## 2. Multi-model AI note

There is no universal ignore-file standard across AI coding tools.

`.claudeignore` works for Claude Code.

When using any other AI tool, paste this file as your first message and follow the
instructions in the "What to ignore" section.

## 3. Documentation map: what to read for each task

Always start with:

- `AGENTS.md`

Then load additional docs only when relevant:

| Task / question | Read these docs | Usually do not need |
|---|---|---|
| Quick repo orientation | `README.md`, `AGENTS.md` | Deep docs under `docs/` unless task requires them |
| Modify MCP server behavior or project-owned code | `AGENTS.md`, `docs/server.md`, `docs/architecture.md` if system design is affected | `docs/deployment.md` unless deploy behavior changes |
| Add, remove, or change hidden operations or visible tools | `AGENTS.md`, `docs/server.md`, `README.md` | Client setup docs unless endpoint/auth changes |
| Add or change configuration, env vars, feature flags, secrets, or runtime settings | `AGENTS.md`, `docs/configuration.md`, `docs/deployment.md` if prod/runtime env is affected | `docs/architecture.md` unless architecture changes |
| Change local setup, test/debug workflow, package dependencies, or tooling | `AGENTS.md`, `docs/development.md`, `requirements.txt`, `Dockerfile` if runtime changes | `docs/deployment.md` unless CI/CD changes |
| Change deployment, Docker, CI/CD, hosting, release flow, rollback, or runtime environment | `AGENTS.md`, `docs/deployment.md`, `docs/cicd.md`, `docs/configuration.md`, `.github/workflows/deploy.yml`, `docker-compose.yml` | Local-only development docs unless needed |
| Investigate bugs, production incidents, Cloudflare/Coolify problems, hangs, or auth failures | `AGENTS.md`, `docs/troubleshooting.md`, `docs/gotchas.md`, relevant architecture/deployment docs, `HANDOFF.md` if present | Client setup docs unless client config is involved |
| Continue unfinished work | `AGENTS.md`, `HANDOFF.md`, relevant docs named inside `HANDOFF.md` | Docs unrelated to the handoff scope |
| Work in client setup docs | `AGENTS.md`, `docs/claude-desktop-setup.md`, `docs/windsurf-roo-setup.md`, `docs/tokens.md` | Server internals unless connection behavior changes |
| Claude Code session | `CLAUDE.md`, then `AGENTS.md` | Other docs unless task requires them |
| Documentation-only cleanup | `AGENTS.md`, `README.md`, affected docs under `docs/` | Source files except as needed to verify accuracy |

This map is intentionally task-based. Do not load every Markdown file by default.

## 4. Repository structure

Code we own:

- `server.py` — Python FastMCP server, auth middleware, audit middleware, status page, tool registry, host command/file/Docker/systemd operations
- `docker-compose.yml` — Coolify service definition for devops-mcp, Cloudflare Tunnel, ContextForge sidecars, and volumes
- `Dockerfile` — Python runtime image with Docker CLI and `nsenter`
- `.github/workflows/deploy.yml` — build, push, and Coolify deploy workflow
- `docs/` — architecture, deployment, configuration, troubleshooting, setup notes
- root docs/config files: `README.md`, `AGENTS.md`, `CLAUDE.md`, ignore files

Generated / runtime:

- `/audit/mcp-audit.log` in the `vj5f76xet05bxwdq4utw1kho_mcp-audit` Docker volume
- Docker image layers in GHCR

Third-party / vendor / framework:

- Python packages from `requirements.txt`
- Docker base image `python:3.12-slim`
- Sidecar image `ghcr.io/ibm/mcp-context-forge:1.0.0-RC2`
- Sidecar image `cloudflare/cloudflared:latest`

Build artifacts and caches:

- `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `build/`, `dist/`, `*.egg-info/`

Scripts:

- No standalone project scripts. Operational checks are documented in `docs/troubleshooting.md`.

Migrations:

- None. This project has no database schema.

Deployment files:

- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/deploy.yml`

## 5. Prime Directive: custom-code boundary

Our custom code lives here:

- `server.py`
- `docs/`
- `.github/workflows/`
- root project docs/config files such as `README.md`, `AGENTS.md`, `CLAUDE.md`, `docker-compose.yml`, `Dockerfile`, `requirements.txt`

Everything else requires justification before touching. Do not scatter project
logic into generated caches, local virtualenvs, vendored package directories, or
runtime logs.

## 6. Core modification inventory

No files outside the project-owned areas above are intentionally patched.

| File | Change made | Why it was necessary | Risk during upgrades |
|---|---|---|---|
| — | — | — | — |

## 7. Task-to-file navigation: what to edit for common changes

| Task | Files to touch | Files not to touch |
|---|---|---|
| Change visible MCP tools or discovery flow | `server.py`, `docs/server.md`, `README.md` | client config docs unless endpoint/auth changes |
| Add a hidden operation | `server.py` (`@_operation`), `README.md`, `docs/server.md` | `_registered_tools` direct tool list unless it must be always-on |
| Change auth behavior | `server.py` (`AuthMiddleware`), `docs/configuration.md`, `docs/troubleshooting.md` | committed token values |
| Add or rotate an agent token | Coolify environment only, `docs/tokens.md` if the agent name list changes | GitHub Secrets, source files, token values in docs |
| Change container privileges, mounts, or sidecars | `docker-compose.yml`, `docs/architecture.md`, `docs/deployment.md` | Coolify-only edits that are not represented in git |
| Change image build or deploy behavior | `.github/workflows/deploy.yml`, `docs/deployment.md`, `docs/cicd.md` | manual server builds |
| Investigate production failure | `docs/troubleshooting.md`, status page, audit log via MCP/Coolify logs | live source edits on the VPS |

## 8. Data model and external identifiers

Do not casually rename or regenerate these identifiers.

| Entity/System | Identifier | Where defined | Notes |
|---|---|---|---|
| GitHub repo | `u2giants/devops-mcp` | GitHub, docs | Source of truth |
| Public MCP endpoint | `https://mcp.designflow.app/mcp` | Cloudflare Tunnel + clients | Streamable HTTP endpoint |
| Public status page | `https://mcp.designflow.app/` and `/status` | `server.py` | Public read-only HTML |
| Legacy SSE mount | `https://mcp.designflow.app/sse/sse` | `server.py` | For older clients; prefer `/mcp` |
| Coolify service UUID | `vj5f76xet05bxwdq4utw1kho` | Coolify, GitHub secret `COOLIFY_SERVICE_UUID`, docs | Production deploy target |
| GHCR image | `ghcr.io/u2giants/devops-mcp` | workflow, compose | Tags: `main`, `sha-<full-sha>` |
| VPS IP | `178.156.180.212` | docs | Coolify host |
| Cloudflare tunnel ID | `aa2bbb47-3907-485d-a0fa-61f57af478d8` | Cloudflare, `docs/deployment.md` | Routes `mcp.designflow.app` |
| Audit volume | `vj5f76xet05bxwdq4utw1kho_mcp-audit` | `docker-compose.yml`, Coolify | Holds `/audit/mcp-audit.log` |

## 9. Container and service inventory

| Container/service | Purpose | Managed by | App/project ID | Image/source |
|---|---|---|---|---|
| `devops-mcp` | FastMCP server with root-equivalent VPS tools | Coolify | `vj5f76xet05bxwdq4utw1kho` | `ghcr.io/u2giants/devops-mcp:main` |
| `cloudflared` | Public tunnel for `mcp.designflow.app` | Coolify compose sidecar | tunnel `aa2bbb47-3907-485d-a0fa-61f57af478d8` | `cloudflare/cloudflared:latest` |
| `contextforge` | Optional ContextForge UI/gateway database | Coolify compose sidecar | same Coolify service | `ghcr.io/ibm/mcp-context-forge:1.0.0-RC2` |
| `contextforge-register` | One-shot registration of devops-mcp with ContextForge | Coolify compose sidecar | same Coolify service | `ghcr.io/ibm/mcp-context-forge:1.0.0-RC2` |
| `cf-cloudflared` | Tunnel for ContextForge | Coolify compose sidecar | same Coolify service | `cloudflare/cloudflared:latest` |

## 10. What to ignore

Do not load these into AI context unless the task explicitly requires them:

- `.git/`
- `.venv/`, `venv/`, `env/`
- `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`
- `build/`, `dist/`, `*.egg-info/`
- `.cache/`, `coverage/`
- local `.env*` files
- audit logs or copied runtime logs

## 11. Intentional quirks and non-obvious decisions

### Always-on tools are intentionally tiny

Looks like:
Most useful operations are missing from `tools/list`.

Actually:
Only `health`, `list_capabilities`, `get_capability_details`, `tool_search`, and
`invoke_tool` are registered as always-on MCP tools. Operations such as
`run_command`, `read_file`, `docker_ps`, and `service_status` live in a hidden
registry and are executed through `invoke_tool`.

Why:
The server has root-level host access. Keeping the schema list small reduces
client context overhead and forces discovery before action.

Do not change because:
Registering every operation directly bloats every AI session and removes the
explicit discovery step that session-level FastMCP instructions now reinforce.

### Catalog/search/detail tools return invocation guidance as data

Looks like:
Catalog/search/detail results duplicate operation names, args, safety metadata,
and pseudo-call strings.

Actually:
This is deliberate client guidance. Some MCP clients see only a small tool list, so
the catalog tools must return enough structured data for the AI to construct the
correct `invoke_tool` call without loading every hidden schema into `tools/list`.

Why:
This keeps tool metadata lazy while still making capabilities discoverable.

Do not change because:
Returning only names makes agents guess argument shapes and increases failed or
unsafe calls. Registering every operation as a real MCP tool reintroduces context
bloat.

### Auth is HTTP middleware, audit is FastMCP middleware

Looks like:
Two middleware systems are unnecessarily split.

Actually:
Bearer-token auth happens in Starlette before MCP handling; audit logging happens
inside FastMCP around tool calls. A `contextvars.ContextVar` carries the agent
identity from the HTTP layer into the MCP layer.

Why:
HTTP auth needs to reject unauthenticated requests before protocol handling, while
audit logging needs tool name, arguments, success, and duration.

Do not change because:
Collapsing these layers can either lose agent identity in audit records or allow
unauthenticated protocol requests deeper into the stack.

### Host commands use `nsenter`

Looks like:
Commands should just run inside the container.

Actually:
`run_command` uses `nsenter --target 1 --mount --uts --ipc --net --pid --` so
commands run in the host namespaces. File operations map host paths through
`/host`.

Why:
The container is a control plane for the VPS, not the target environment.

Do not change because:
Running commands only inside the container would make systemd, host files, and
host networking diagnostics misleading or impossible.

### Process timeouts kill the process group

Looks like:
`subprocess.run(..., timeout=...)` would be simpler.

Actually:
The code starts a new process session and kills the whole process group on
timeout.

Why:
Pipelines, SSH, Docker, and shell commands can leave grandchildren holding stdout
pipes open after the parent shell dies.

Do not change because:
Killing only bash reintroduces hangs where the MCP call never returns.

### Cloudflare Tunnel is the public routing path

Looks like:
Coolify/Traefik labels should explain public HTTPS routing.

Actually:
`mcp.designflow.app` reaches the service through a Cloudflare Tunnel sidecar.
Traefik is not the public path for this service.

Why:
The VPS does not expose an inbound public route directly for this endpoint.

Do not change because:
Troubleshooting 502s through Traefik wastes time; check `cloudflared` and the
backend container first.

## 12. Credentials and environment

Never commit secret values.

| Variable | Purpose | Stored where | Required in dev | Required in prod |
|---|---|---|---|---|
| `PORT` | Uvicorn listen port | Docker/Coolify env | no | yes (`8765`) |
| `BIND_HOST` | Uvicorn bind host | Docker/Coolify env | no | no (`0.0.0.0`) |
| `HOST_ROOT` | Host filesystem mount inside container | Docker/Coolify env | no | yes (`/host`) |
| `AUDIT_LOG_PATH` | JSONL audit file path | Docker/Coolify env | no | yes (`/audit/mcp-audit.log`) |
| `MAX_OUTPUT_CHARS` | Max command output returned | Coolify env if overridden | no | no |
| `DEFAULT_TIMEOUT` | Default host command timeout | Coolify env if overridden | no | no |
| `TOKEN_CLAUDE` | Claude bearer token | Coolify env | optional | optional |
| `TOKEN_GEMINI` | Gemini bearer token | Coolify env | optional | optional |
| `TOKEN_CHATGPT` | ChatGPT bearer token | Coolify env | optional | optional |
| `TOKEN_CODEX` | Codex bearer token | Coolify env | optional | optional |
| `TOKEN_ROOCODE` | Roo Code bearer token | Coolify env | optional | optional |
| `CLOUDFLARE_TUNNEL_TOKEN` | Public MCP tunnel token | Coolify env | no | yes |
| `CF_GW_TUNNEL_TOKEN` | ContextForge tunnel token | Coolify env | no | yes if ContextForge tunnel is used |
| `CF_JWT_SECRET` | ContextForge JWT secret | Coolify env | no | yes if ContextForge is enabled |
| `CF_AUTH_SECRET` | ContextForge auth encryption secret | Coolify env | no | yes if ContextForge is enabled |
| `CF_ADMIN_EMAIL` | ContextForge admin email | Coolify env | no | yes if ContextForge is enabled |
| `CF_ADMIN_PASSWORD` | ContextForge admin password/basic auth password | Coolify env | no | yes if ContextForge is enabled |

## 13. Deployment

Real deployment path:

- GitHub Actions workflow: `Build and Deploy` in `.github/workflows/deploy.yml`
- Trigger: push to `main`
- Image: `ghcr.io/u2giants/devops-mcp`
- Tags: `main` and `sha-<full_commit_sha>`
- Platform: Coolify service UUID `vj5f76xet05bxwdq4utw1kho`
- Deploy trigger: workflow calls `GET $COOLIFY_BASE_URL/api/v1/deploy?uuid=$COOLIFY_SERVICE_UUID` with `COOLIFY_API_TOKEN`
- Runtime environment: Coolify service environment variables
- Rollback: pin `docker-compose.yml` to a `sha-<full_commit_sha>` image tag, commit, push, then let Coolify redeploy; or redeploy a previous Coolify deployment if available
- SSH: not routine. Do not edit source or build images on the VPS. Use Coolify logs/terminal only for exceptional diagnosis.

## 14. Critical incidents

### 2026-05-28 Long-running file/command calls could hang MCP workers

What happened:
Large `read_file`, recursive `list_directory`, audit-log reads, and commands with
child processes could block longer than expected.

Impact:
Clients saw timeouts or stalled tool calls, and the server could spend excessive
memory or time on large host files/logs.

Root cause:
Some code paths materialized unbounded data or killed only the parent shell on
timeout.

Recovery:
File and audit reads now stream bounded windows; recursive listing is bounded;
host command execution kills the whole process group.

Rule added to prevent recurrence:
Keep reads bounded and kill process groups, not only shell parents.

### 2026-06-05 GitHub SSH deploy path timed out

What happened:
GitHub Actions could build the image but SSH-based deployment to the VPS timed out.

Impact:
Successful images did not reliably reach production through the old workflow.

Root cause:
The deploy workflow depended on inbound SSH reachability from GitHub runners.

Recovery:
The workflow now deploys by calling the Coolify API after pushing GHCR images.

Rule added to prevent recurrence:
Deployment is GitHub Actions to GHCR to Coolify API. Do not reintroduce SSH as
the normal deploy path.

## 15. Pending work

| Status | Item | Owner/next action |
|---|---|---|
| open | Update GitHub Actions versions if Node.js 20 action deprecation warnings become failing errors | Maintainer: bump affected marketplace actions and rerun workflow |
| done | Add capability browsing, detail contracts, structured search, safety metadata, examples, and better invocation errors | Completed in this change |
| done | Add FastMCP session-level discovery instructions and explicit operation descriptions | Completed in commit `a849ff4` |

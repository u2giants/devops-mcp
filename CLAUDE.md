# DevOps MCP — Rules for AI Agents

## Deployment Rules (STRICT — no exceptions)

**GitHub is the source of truth. Never edit code directly on the server.**

```
edit code locally
  → commit to main (no branches, no PRs)
  → GitHub Actions builds Docker image
  → pushes to GHCR (:main + :sha-<commit>)
  → triggers Coolify API → Coolify pulls image → live
```

- **No branches.** All commits go directly to `main`.
- **No live edits.** Do not `ssh` into the VPS and edit `server.py` or any other source file. The server copy is a deployment artifact, not a workspace.
- **Coolify is a consumer of pre-built images.** It pulls from GHCR. It does not build. Do not run `docker build` on the server.
- **All secrets in GitHub Secrets.** Tokens, API keys, SSH keys — none in code, none in committed `.env` files. See [docs/cicd.md](docs/cicd.md) for the full secret list.

## Live URL

`https://mcp.designflow.app/mcp`
`https://mcp.designflow.app/sse/sse?token=YOUR_TOKEN_HERE`

## What this is

MCP server giving AI agents full VPS access for devops/sysadmin tasks. Runs as a
Docker container managed by Coolify. Authenticates callers via per-agent bearer tokens.

## Docs

| File | What it covers |
|---|---|
| [docs/cicd.md](docs/cicd.md) | Full deployment pipeline, GitHub Secrets, image tags |
| [docs/deployment.md](docs/deployment.md) | Coolify config, adding tokens, networking |
| [docs/tokens.md](docs/tokens.md) | Current token list, how to add/revoke agents |
| [docs/windsurf-roo-setup.md](docs/windsurf-roo-setup.md) | Windsurf & Roo Code MCP config |
| [docs/server.md](docs/server.md) | server.py walkthrough |
| [docs/architecture.md](docs/architecture.md) | nsenter, middleware, Traefik |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems and fixes |
| [docs/gotchas.md](docs/gotchas.md) | Things that will bite you |

## Quick reference

| Item | Value |
|---|---|
| GitHub repo | `u2giants/devops-mcp` |
| GHCR image | `ghcr.io/u2giants/devops-mcp:main` |
| Coolify service UUID | `vj5f76xet05bxwdq4utw1kho` |
| Coolify URL | `https://coolify.designflow.app` |
| VPS IP | `178.156.180.212` |
| Container name | `devops-mcp-vj5f76xet05bxwdq4utw1kho` |
| Audit volume | `vj5f76xet05bxwdq4utw1kho_mcp-audit` |

---

## Docker Container Naming on this VPS

All containers on this VPS are managed by Coolify, which names them using internal UUIDs (e.g., `server-rd261bt0wy7ifjrkoe1tkl92-101538519687`). To keep things readable, a systemd service automatically renames every container to a human-friendly name the moment it starts — surviving every redeploy, restart, or server reboot.

**How it works:**
- Script: `/usr/local/bin/docker-rename-containers.sh`
- Systemd service: `docker-rename-containers-watch` (runs permanently, watches Docker start events)
- On any container start event, the script checks the name against its map and renames it immediately

**Current name map** (UUID/Coolify name → readable name):

| Coolify name (prefix match) | Readable name |
|---|---|
| `server-rd261bt0wy7ifjrkoe1tkl92*` | `twenty-server` |
| `worker-rd261bt0wy7ifjrkoe1tkl92*` | `twenty-worker` |
| `g5j115bwrn8125ev6ap1tjrv` | `twenty-postgres` |
| `jht51gt0biykivnama17crlt` | `twenty-redis` |
| `g5j115bwrn8125ev6ap1tjrv-proxy` | `twenty-nginx-proxy` |
| `lrddgp8im0276gllujfu7wm3*` | `synology-monitor-web` |
| `efl17f5iocnz94840pexre9d*` | `synology-nas-mcp` |
| `openmanus-backend-e10kwzww46ljhrgz1qj08j6a*` | `openmanus-backend` |
| `open-webui-e10kwzww46ljhrgz1qj08j6a*` | `openmanus-open-webui` |
| `novnc-e10kwzww46ljhrgz1qj08j6a*` | `openmanus-novnc` |
| `devops-mcp-vj5f76xet05bxwdq4utw1kho*` | `devops-mcp` |
| `cloudflared-vj5f76xet05bxwdq4utw1kho*` | `devops-mcp-cloudflared` |
| `cf-cloudflared-vj5f76xet05bxwdq4utw1kho*` | `devops-mcp-cloudflared-cf` |
| `contextforge-vj5f76xet05bxwdq4utw1kho*` | `devops-mcp-contextforge` |

**When a new container is added to this project:**

1. Find its Coolify-assigned name: `docker ps --format "{{.Names}}"`
2. Open the rename script: `sudo nano /usr/local/bin/docker-rename-containers.sh`
3. Add an entry to the appropriate map:
   - If the name ends in a build number suffix (e.g., `-101538519687`), use `PREFIX_RENAMES` with the stable prefix
   - If the name is fixed (e.g., a database UUID with no suffix), use `RENAMES` with the exact name
4. Decide on a readable name following the pattern `{project}-{function}` (e.g., `twenty-postgres`, `openmanus-backend`)
5. The watcher picks up script changes immediately — no restart needed
6. Run `sudo /usr/local/bin/docker-rename-containers.sh` to apply to any already-running containers
7. Update the name map table in this file and in every other project's CLAUDE.md on this VPS

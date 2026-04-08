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

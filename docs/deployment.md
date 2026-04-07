# Deployment

## Overview

The server runs as a Docker container managed by Coolify on the VPS. Coolify uses
the `docker-compose.yml` in this repo to define the service. The image is built by
GitHub Actions and pushed to GHCR — Coolify pulls it, it does not build.

**To deploy:** push to `main`. That's it. See [cicd.md](cicd.md).

---

## Coolify service

| Item | Value |
|---|---|
| Service name | `devops-mcp` |
| Coolify UUID | `vj5f76xet05bxwdq4utw1kho` |
| Coolify UI | https://coolify.designflow.app → DevOps MCP |
| Container name | `devops-mcp-vj5f76xet05bxwdq4utw1kho` |
| Image | `ghcr.io/u2giants/devops-mcp:main` |
| Public URL | `https://mcp.designflow.app` |

---

## Adding a new agent token

1. Generate a token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Coolify UI → DevOps MCP → Environment Variables → Add `TOKEN_<NAME>=<value>` → Save
3. Coolify restarts the container automatically with the new token active
4. Update [docs/tokens.md](tokens.md) and commit to `main`

Tokens are **not** stored in GitHub Secrets or any committed file.

---

## Networking

Routing uses a Cloudflare Tunnel — the same pattern as `ocgate` and `ocmc`.

```
client → Cloudflare edge → cloudflared container → devops-mcp:8765
```

The `cloudflared` sidecar in `docker-compose.yml` opens an outbound tunnel to
Cloudflare using `CLOUDFLARE_TUNNEL_TOKEN`. No inbound ports need to be open on
the VPS firewall.

| Item | Value |
|---|---|
| Tunnel name | `devops-mcp` |
| Tunnel ID | `aa2bbb47-3907-485d-a0fa-61f57af478d8` |
| Tunnel ingress | `mcp.designflow.app` → `http://devops-mcp:8765` |

DNS: `mcp.designflow.app` → CNAME → `aa2bbb47-3907-485d-a0fa-61f57af478d8.cfargotunnel.com`
(proxied, orange cloud on). Managed in Cloudflare DNS under `designflow.app`.

`CLOUDFLARE_TUNNEL_TOKEN` is stored in Coolify's environment variables for this
service (not in code). To rotate: generate a new tunnel token in the Cloudflare
dashboard → update in Coolify env vars → restart.

---

## Volumes

| Volume | Contents | Survives container recreate? |
|---|---|---|
| `vj5f76xet05bxwdq4utw1kho_mcp-audit` | Audit log (`mcp-audit.log`) | Yes |

Do not delete this volume — it contains the historical audit trail.

---

## Rollback

Find the commit SHA you want from the GHCR image list or `git log`, then:

1. Edit `docker-compose.yml`: change `image:` to `ghcr.io/u2giants/devops-mcp:sha-<that_sha>`
2. Commit to `main` and push
3. CI runs, Coolify pulls the pinned image, deploys it

Revert to latest: change `image:` back to `ghcr.io/u2giants/devops-mcp:main`.

---

## Infrastructure IDs

| Item | Value |
|---|---|
| VPS IP | `178.156.180.212` |
| Coolify URL | `https://coolify.designflow.app` |
| Coolify service UUID | `vj5f76xet05bxwdq4utw1kho` |
| Container name | `devops-mcp-vj5f76xet05bxwdq4utw1kho` |
| Audit volume | `vj5f76xet05bxwdq4utw1kho_mcp-audit` |
| GHCR image | `ghcr.io/u2giants/devops-mcp:main` |
| GitHub repo | `https://github.com/u2giants/devops-mcp` |
| Public URL | `https://mcp.designflow.app` |
| DNS zone | `designflow.app` (Cloudflare) |

---

## The old gemini-mcp service

`/etc/systemd/system/gemini-mcp.service` and `/home/ai/gemini-mcp/` still exist on
disk. The service is stopped and disabled. Do not re-enable it — it conflicts with
devops-mcp on port 8765.

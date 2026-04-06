# Deployment

## Overview

The server runs as a Docker container on the VPS. It is **not** managed by Coolify's
normal deployment pipeline — it was started manually with `docker run` and has Coolify
labels so it shows up in Coolify's UI.

This is the most important operational fact about this system.

---

## Why it's not fully managed by Coolify

Coolify's normal deployment flow (for services) uses `docker compose up` from a compose
file it stores internally. That works well for standard apps. Our container needs:

- `privileged: true`
- `pid: host`
- A mount of the entire host root filesystem (`/:/host`)
- Specific Traefik labels for HTTPS routing
- All five token env vars injected at runtime

Coolify's service API in its current version (4.0.0-beta.470) cannot reliably re-apply
all of these on restart/redeploy via its own orchestration — it kept creating the
container without the Traefik labels or with missing network attachments. The solution
was to start the container manually with `docker run`, which gives exact control, and
add Coolify's own labels so it appears in the UI.

**The consequence:** when CI/CD triggers "restart" via the Coolify API, Coolify restarts
the existing container. It does NOT pull a new image or recreate the container. A new
image from GitHub Actions will only take effect when the container is manually replaced.

---

## The `docker run` command

This is the full command used to start the container. It must be re-run whenever:
- A new image needs to be deployed
- New tokens are added
- Any container configuration changes

```bash
UUID="vj5f76xet05bxwdq4utw1kho"
DOMAIN="mcp.designflow.app"
PORT="8765"

docker rm -f devops-mcp-${UUID}

docker run -d \
  --name devops-mcp-${UUID} \
  --restart always \
  --privileged \
  --pid host \
  --network coolify \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /:/host:rw \
  -v ${UUID}_mcp-audit:/audit \
  -e PORT=$PORT \
  -e HOST_ROOT=/host \
  -e AUDIT_LOG_PATH=/audit/mcp-audit.log \
  -e TOKEN_CLAUDE=wl6Uxf9dlZ981eNF_d8M7EQXbkI56fvtZV-5i0nWa0k \
  -e TOKEN_GEMINI=TpZbQejvI3Wfu9i99rDgLnAnr8BLLWgihsT-oY0NP6E \
  -e TOKEN_CHATGPT=z_RV85gZIUd4mN6xaQ3-puPnCuVzVX6GIcsZ_jYqMpk \
  -e TOKEN_CODEX=0Aaq7Qxb4EezlZBn0eOqy-b0XErOP8AcvfUNJ8V1cFc \
  -e TOKEN_ROOCODE=xBY2IHFwVfXnVUZ3rwfs-zW0jdf4BO2oO8iB1TjRs-0 \
  -e COOLIFY_RESOURCE_UUID=$UUID \
  -e COOLIFY_CONTAINER_NAME=devops-mcp-${UUID} \
  -e SERVICE_NAME_DEVOPS_MCP=devops-mcp \
  -l coolify.managed=true \
  -l coolify.type=service \
  -l coolify.name=devops-mcp-${UUID} \
  -l coolify.resourceName=devops-mcp \
  -l coolify.serviceName=devops-mcp \
  -l coolify.environmentName=production \
  -l "traefik.enable=true" \
  -l "traefik.http.middlewares.gzip.compress=true" \
  -l "traefik.http.middlewares.redirect-to-https.redirectscheme.scheme=https" \
  -l "traefik.http.routers.http-0-${UUID}.entryPoints=http" \
  -l "traefik.http.routers.http-0-${UUID}.middlewares=redirect-to-https" \
  -l "traefik.http.routers.http-0-${UUID}.rule=Host(\`${DOMAIN}\`) && PathPrefix(\`/\`)" \
  -l "traefik.http.routers.http-0-${UUID}.service=http-0-${UUID}" \
  -l "traefik.http.routers.https-0-${UUID}.entryPoints=https" \
  -l "traefik.http.routers.https-0-${UUID}.middlewares=gzip" \
  -l "traefik.http.routers.https-0-${UUID}.rule=Host(\`${DOMAIN}\`) && PathPrefix(\`/\`)" \
  -l "traefik.http.routers.https-0-${UUID}.service=https-0-${UUID}" \
  -l "traefik.http.routers.https-0-${UUID}.tls=true" \
  -l "traefik.http.routers.https-0-${UUID}.tls.certresolver=letsencrypt" \
  -l "traefik.http.services.http-0-${UUID}.loadbalancer.server.port=${PORT}" \
  -l "traefik.http.services.https-0-${UUID}.loadbalancer.server.port=${PORT}" \
  ghcr.io/u2giants/devops-mcp:main
```

> **Keep this command updated.** Any time you add a token or change configuration,
> update this command in this file and in the repo, then re-run it.

---

## Coolify UUID

The Coolify service UUID is `vj5f76xet05bxwdq4utw1kho`. This appears:
- In the container name: `devops-mcp-vj5f76xet05bxwdq4utw1kho`
- In the audit volume name: `vj5f76xet05bxwdq4utw1kho_mcp-audit`
- In Traefik router/service labels
- In Coolify API calls: `GET /api/v1/services/vj5f76xet05bxwdq4utw1kho/restart`

Do not change this UUID unless you are recreating the entire Coolify service entry.

---

## Deploying a new image

After CI pushes a new image to GHCR, deploying it requires:

```bash
docker pull ghcr.io/u2giants/devops-mcp:main
# then re-run the full docker run command above
```

You must be authenticated to GHCR first:
```bash
echo "<github_token>" | docker login ghcr.io -u u2giants --password-stdin
```

The GitHub token is stored in `/home/ai/.netrc`. The Docker login credentials are
cached in `/home/ai/.docker/config.json` after first login — subsequent pulls should
not require re-authentication unless the token expires.

---

## Adding a new agent token

1. Generate a token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Add it to Coolify's env vars (so it's recorded there):
   ```bash
   curl -X POST http://127.0.0.1:8000/api/v1/services/vj5f76xet05bxwdq4utw1kho/envs \
     -H "Authorization: Bearer <coolify_token>" \
     -H "Content-Type: application/json" \
     -d '{"key":"TOKEN_NEWAGENT","value":"<generated_token>"}'
   ```
3. Add `-e TOKEN_NEWAGENT=<generated_token>` to the `docker run` command
4. Re-run the `docker run` command to restart the container with the new token
5. Update the `docker run` command in this file

---

## Networking

### Docker networks

The container is attached to the `coolify` Docker bridge network. This is the network
that Traefik monitors for routing targets. The container does NOT have a directly
exposed port to the host — all traffic goes through Traefik.

Port 8765 is the internal port where the MCP server listens. It is exposed within
the Docker network but not on the host (`0.0.0.0:8765` is NOT bound — unlike earlier
in the setup, the final deployment uses `--network coolify` without `-p`).

### Traefik

The `coolify-proxy` container runs Traefik and watches the Docker socket for containers
with `traefik.enable=true`. When our container starts, Traefik picks up its labels
within seconds and begins routing `mcp.designflow.app` to it.

TLS certificates are issued automatically by Let's Encrypt via the `letsencrypt`
cert resolver configured in Traefik. The certificate is stored in Traefik's ACME
storage (inside the `coolify-proxy` container's volume) and auto-renewed.

### DNS

`mcp.designflow.app` has an A record pointing to `178.156.180.212` (the VPS IP),
managed in Cloudflare. It is **not** proxied through Cloudflare (orange cloud is off) —
traffic goes directly to the server. This is intentional for MCP/SSE connections, which
can be sensitive to proxy timeouts.

---

## Volumes

| Volume name | Contents | Survives container restart? |
|---|---|---|
| `vj5f76xet05bxwdq4utw1kho_mcp-audit` | Audit log (`mcp-audit.log`) | Yes |

The audit log volume is a named Docker volume. It persists even if the container is
removed and recreated, as long as the same volume name is used in the `docker run`
command. Do not delete this volume — it contains the historical audit trail.

---

## The old gemini-mcp service

Before this system, there was a systemd service called `gemini-mcp` running at
`/home/ai/gemini-mcp/server.py`. It ran as the `ai` user, was restricted to
`/home/ai`, and was specifically integrated with Gemini.

It was stopped and disabled during the devops-mcp setup because:
- It occupied port 8765, conflicting with the new container
- The new devops-mcp server replaces all its functionality and supports all AI tools

The service file still exists at `/etc/systemd/system/gemini-mcp.service` and the
code at `/home/ai/gemini-mcp/`. Do not re-enable it — it will conflict with
devops-mcp on port 8765.

---

## Infrastructure IDs (keep updated)

| Item | Value |
|---|---|
| VPS IP | 178.156.180.212 |
| Coolify URL | https://coolify.designflow.app |
| Coolify service UUID | vj5f76xet05bxwdq4utw1kho |
| Container name | devops-mcp-vj5f76xet05bxwdq4utw1kho |
| Audit volume | vj5f76xet05bxwdq4utw1kho_mcp-audit |
| GHCR image | ghcr.io/u2giants/devops-mcp:main |
| GitHub repo | https://github.com/u2giants/devops-mcp |
| Public URL | https://mcp.designflow.app |
| DNS zone | designflow.app (Cloudflare) |

# CI/CD

## Flow

```
git push origin main
      │
      ▼
GitHub Actions (.github/workflows/deploy.yml)
      │
      ├── docker build
      ├── docker push ghcr.io/u2giants/devops-mcp:main
      ├── docker push ghcr.io/u2giants/devops-mcp:sha-<commit>
      │
      └── SSH into VPS as ai@178.156.180.212
            │
            └── docker compose pull devops-mcp
                docker compose up -d --no-deps devops-mcp
                (updates ONLY devops-mcp — cloudflared/contextforge untouched)
```

Push to `main` is the only deployment action. No manual steps on the server.

## Rules

- **No branches.** Commit directly to `main`.
- **No live edits on the server.** GitHub is the source of truth.
- **Coolify pulls pre-built images.** It does not build from source.
- **All secrets in GitHub Secrets.** Never in committed files.

## GitHub Secrets

Set on `u2giants/devops-mcp` (Settings → Secrets → Actions):

| Secret | Value | Used for |
|---|---|---|
| `VPS_SSH_KEY` | Private key for `github-actions-devops-mcp` | SSH into VPS to run docker compose |
| `VPS_HOST` | `178.156.180.212` | VPS IP for SSH |

The corresponding public key is in `/home/ai/.ssh/authorized_keys` on the VPS.

`GITHUB_TOKEN` is automatic — no setup needed. Used to push to GHCR.

`GITHUB_TOKEN` is automatic — no setup needed. Used to push to GHCR.

## Image tags

Every push to `main` produces two tags:
- `:main` — always the latest build from main
- `:sha-<full_commit_sha>` — immutable, for rollbacks

Rollback: update the `image:` field in `docker-compose.yml` to `ghcr.io/u2giants/devops-mcp:sha-<that_sha>`, commit to main, push.

## Token management

Agent tokens (`TOKEN_CLAUDE`, `TOKEN_GEMINI`, etc.) are stored as environment variables
in Coolify's service configuration — **not** in GitHub Secrets and not in any committed
file. To add or rotate a token:

1. In Coolify UI: DevOps MCP → Environment Variables → add/edit `TOKEN_<NAME>` → Save
2. Coolify automatically restarts the container with the new env var

No code change or push needed for token changes.

## Build cache

The workflow uses GitHub Actions cache (`type=gha`) for Docker layer caching.
Unchanged layers build in seconds. First build after a long gap is ~2 min.

## Upcoming: Node.js deprecation (deadline: June 2026)

The workflow uses `docker/build-push-action@v6`, `docker/login-action@v3`, and
`docker/setup-buildx-action@v3` which run on Node.js 20. GitHub forces Node.js 24
starting June 2, 2026. Update these to v7+/v4+/v4+ before then.

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
      └── POST https://coolify.designflow.app/api/v1/services/vj5f76xet05bxwdq4utw1kho/restart
                │
                ▼
          Coolify restarts the existing container
          (does NOT pull new image — see note below)
```

## Important limitation

The Coolify "restart" API call restarts the existing container. It does **not**:
- Pull the new image from GHCR
- Recreate the container

This means after a push, you must manually pull the new image and re-run the
`docker run` command to actually deploy it. See [deployment.md](deployment.md)
for the full command.

This is a known gap. A future improvement would be to write a small deploy script
on the VPS and have GitHub Actions call it via SSH instead of using the Coolify API.

## GitHub secrets

Set on the `u2giants/devops-mcp` repo:

| Secret | Value | Used for |
|---|---|---|
| `COOLIFY_API_TOKEN` | Coolify API bearer token | Authenticating the restart call |
| `COOLIFY_BASE_URL` | `https://coolify.designflow.app` | Base URL for Coolify API |
| `COOLIFY_SERVICE_UUID` | `vj5f76xet05bxwdq4utw1kho` | Which service to restart |

## Image tags

Every push to `main` produces two tags:
- `:main` — always the latest build from main
- `:sha-<full_commit_sha>` — immutable, for rollbacks

To roll back to a previous version, find the commit SHA you want, then use
`ghcr.io/u2giants/devops-mcp:sha-<that_sha>` in the `docker run` command.

## Build cache

The workflow uses GitHub Actions cache (`type=gha`) for Docker layer caching.
Subsequent builds of unchanged layers are near-instant. The first build after a
new runner picks up the job, or after a long gap, will be slower (~2 min).

## Branch strategy

No branches. All changes go directly to `main`. Each push triggers a build.
This matches the pattern used by all other projects in this setup (openclaw,
twenty-server, etc.).

## Node.js deprecation warning

GitHub Actions currently shows:
```
Node.js 20 actions are deprecated... Actions will be forced to run with Node.js 24
by default starting June 2nd, 2026.
```

This affects `docker/build-push-action@v6`, `docker/login-action@v3`, and
`docker/setup-buildx-action@v3`. Before June 2026, update these to their latest
versions (v7+, v4+, v4+ respectively) to avoid build failures.

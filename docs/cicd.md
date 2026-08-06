# CI/CD

## Flow

```
git push origin main
      │
      ▼
GitHub Actions (.github/workflows/deploy.yml)
      │
      ├── install exactly from uv.lock
      ├── report dependency versions
      ├── run baseline tests
      │     │
      │     └── build is blocked unless tests pass
      ├── docker build
      ├── docker push ghcr.io/u2giants/devops-mcp:main
      ├── docker push ghcr.io/u2giants/devops-mcp:sha-<commit>
      │
      └── Call Coolify API /api/v1/deploy?uuid=<service_uuid>
            │
            └── Coolify pulls the latest GHCR :main image and redeploys the service
```

Push to `main` is the only deployment action. No manual steps on the server.

## Rules

- **No branches.** Commit directly to `main`.
- **No live edits on the server.** GitHub is the source of truth.
- **Coolify pulls pre-built images.** It does not build from source.
- **All secrets in GitHub Secrets.** Never in committed files.
- **Locked dependencies only.** CI and Docker must fail when `pyproject.toml` and
  `uv.lock` disagree.
- **Tests before publishing.** The image job depends on the test job, so no GHCR
  push or Coolify deployment can begin after a failed test.

## GitHub Secrets

Set on `u2giants/devops-mcp` (Settings → Secrets → Actions):

| Secret | Value | Used for |
|---|---|---|
| `COOLIFY_API_TOKEN` | Coolify API token | Queue deployment after GHCR image push |
| `COOLIFY_BASE_URL` | `https://coolify.designflow.app` | Coolify API base URL |
| `COOLIFY_SERVICE_UUID` | `vj5f76xet05bxwdq4utw1kho` | Service/resource UUID to deploy |
| `VPS_SSH_KEY` | Private key for `github-actions-devops-mcp` | Legacy SSH deploy path; currently unused |
| `VPS_HOST` | `178.156.180.212` | Legacy SSH deploy path; currently unused |

The corresponding public key is in `/home/ai/.ssh/authorized_keys` on the VPS.

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

## GitHub Actions runtime warning

If GitHub Actions warns that one of the marketplace actions is still running on a
deprecated Node.js runtime, bump the affected action versions and rerun the
workflow. Keep the deploy flow itself the same: build/push GHCR, then call the
Coolify API.

# CLAUDE.md

Read [AGENTS.md](AGENTS.md) first. It is the canonical operating guide for this
repo and applies to every AI coding session. This file is Claude Code-specific.

## Claude Code notes

- `.claudeignore` is the active Claude Code ignore file. It excludes virtualenvs,
  Python caches, build outputs, logs, local env files, and coverage/cache folders.
- Do not load audit logs or copied runtime logs unless the task explicitly asks
  for audit investigation.
- Keep the MCP lazy-discovery pattern: visible tools stay limited to `health`,
  `list_capabilities`, `get_capability_details`, `tool_search`, and `invoke_tool`.

## Allowed operations

- Edit project files under `server.py`, `docs/`, `.github/workflows/`, and root
  config/docs files.
- Run local checks such as `python -m py_compile server.py`, import smoke tests,
  and Docker image builds.
- Commit directly to `main` when the user asks for implementation/deployment work.

## Deployment and SSH

GitHub is the source of truth. Normal deployment is:

```text
commit to main -> GitHub Actions -> GHCR -> Coolify API -> production
```

SSH is not the normal deployment path. Do not edit source, build images, or patch
containers on the VPS except for exceptional diagnosis explicitly requested by the
owner. Use Coolify logs/terminal for runtime inspection when needed.

## Host/OS Change Routing (STRICT)

DevOps MCP is diagnostic and emergency tooling. Durable host/OS changes are owned
by the canonical Ansible repo: `/worksp/ansible`
([u2giants/ansible](https://github.com/u2giants/ansible)).

Do **not** use MCP root access for durable infra changes. Make a PR in
`/worksp/ansible` and let GitHub Actions apply it. This includes packages, users,
firewall, SSH/sudo, Docker engine or daemon config, systemd units/timers, cron,
`/etc`, `/usr/local/bin`, `/usr/local/sbin`, Cloudflare Tunnel 1, Coolify host
glue, and the backup/DNS watchdogs.

Break-glass direct host repair is allowed only when needed to restore service.
Follow it with an Ansible PR that captures or reconciles the drift. Warn-mode
policy reminders may appear during MCP use, but they do not replace the
PR/apply flow.

## Commit style

- Commit directly to `main`; no feature branches.
- Use concise subjects such as `docs: update developer guide` or
  `server: add operation`.
- Include a short body when the why is not obvious.

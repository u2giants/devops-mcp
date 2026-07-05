# Gotchas and known issues

Things that will bite you if you don't know about them.

---

## 1. Never edit code on the server

**This is the most important rule.**

GitHub is the source of truth. Do not SSH in and edit `server.py` or any other source
file directly. Changes made on the server are overwritten on the next Coolify redeploy.

**The fix:** edit locally → commit to `main` → push. CI builds the image, Coolify
pulls it, done.

---

## 2. Durable host changes go through Ansible

DevOps MCP is diagnostic and emergency tooling. Durable host/OS changes belong in
`/worksp/ansible` ([u2giants/ansible](https://github.com/u2giants/ansible)) and
are applied by GitHub Actions.

Do not use MCP root access to make lasting infra changes to packages, users,
firewall, SSH/sudo, Docker engine or daemon config, systemd units/timers, cron,
`/etc`, `/usr/local/bin`, `/usr/local/sbin`, Cloudflare Tunnel 1, Coolify host
glue, or the backup/DNS watchdogs. Make an Ansible PR instead.

Break-glass direct repair is allowed only to restore service. Afterward, open an
Ansible PR to capture or reconcile the drift. Warn-mode policy reminders are just
reminders; they do not replace the PR/apply flow.

---

## 3. Adding a token does NOT require a code push

Tokens are Coolify environment variables, not code. To add or rotate a token:

Coolify UI → DevOps MCP → Environment Variables → add `TOKEN_<NAME>` → Save

Coolify restarts the container with the new env var automatically. No commit needed.

---

## 4. The docker-compose.yml in this repo is the source of truth for container config

Coolify uses `docker-compose.yml` to define volumes, capabilities, mounts, and image.
If you need to change container configuration (e.g. add a volume, change a capability),
edit `docker-compose.yml` and push to `main`. Do not change these things in the
Coolify UI — those changes will be lost on the next git-triggered redeploy.

## 4. Coolify deploy API is the normal redeploy path

The GitHub workflow calls Coolify's deploy API after pushing the GHCR image. Use
that path for normal releases. If `docker-compose.yml` adds or removes services,
verify the Coolify deployment recreated the stack from the updated compose file.

---

## 6. Routing goes through Cloudflare Tunnel — not Traefik

`mcp.designflow.app` is routed via the `cloudflared` sidecar container, identical
to `ocgate` and `ocmc`. DNS is a proxied CNAME to the tunnel ID, not an A record
to the VPS IP. Traefik/Coolify proxy plays no role in routing public traffic.

If the endpoint returns 503, the issue is almost always the `cloudflared` container,
not Coolify configuration. Check with: `docker logs devops-mcp-cloudflared-1`

---

## 7. The old gemini-mcp service is still on disk

`/etc/systemd/system/gemini-mcp.service` and `/home/ai/gemini-mcp/` still exist.
The service is stopped and disabled. Do not re-enable it — it will conflict with
devops-mcp on port 8765.

The old service ran as the `ai` user with restricted access to `/home/ai`. The new
one runs as root with full host access. They are not compatible.

---

## 8. `write_file` overwrites the entire file

The `write_file` tool replaces the entire file contents. It is not a patch or diff.
If an AI calls `write_file("/etc/nginx/nginx.conf", content)`, it must provide the
complete file content — not just the changed lines.

The `make_backup=True` default saves a timestamped `.bak` file before overwriting.
These backups accumulate in the same directory as the file. Nobody cleans them up.
Over time, directories with frequently-edited files will fill with `.bak` files.

---

## 9. `run_command` output is capped at 60,000 characters

Commands that produce very long output (e.g. `cat large_file`, `docker logs` with
thousands of lines, `find / -name "*.log"`) will be truncated. The response includes
`stdout_truncated: true` when this happens.

For large outputs, either redirect to a file on the host and use `read_file` to page
through it, or use options to limit output (`tail -n 100`, `grep` filters, etc.).

---

## 10. The status page is unauthenticated

`https://mcp.designflow.app/` is publicly readable. It shows:
- Which agent names are registered (but not their tokens)
- Recent activity (what commands were run and by which agent)
- The list of available tools

This is intentional — it's useful for the owner to check without needing a token.
But be aware that anyone on the internet can see the recent audit log entries,
including command arguments. Avoid running commands with secrets in them (passwords
in command-line args, etc.).

---

## 11. nsenter silently fails without `pid: host`

If the container is started without `--pid host`, `nsenter --target 1` will enter
the container's own init process (PID 1 inside the container, not the host). Commands
will appear to run but will execute inside the container's minimal filesystem and find
nothing. There's no error — they just silently run in the wrong place.

To verify nsenter is working correctly:
```bash
run_command("hostname")
# Should return the host's hostname (e.g. "pop-16gb-VA"), not the container ID
```

---

## 12. The `cwd` parameter in `run_command` is not fully wired through nsenter

The `run_command` tool accepts a `cwd` parameter. In container mode, the intended
working directory is passed as an env var (`NSENTER_CWD`) but the nsenter command
itself always runs from `/`. The bash command inside nsenter does NOT automatically
`cd` to the requested directory.

If you need a command to run in a specific directory, include the `cd` explicitly:
```
run_command("cd /home/ai/myproject && git status")
```

---

## 13. Double middleware application

In `create_app()`, the auth middleware is applied to both the outer Starlette app
and the inner FastMCP app. This is needed to make the public status page work while
keeping the MCP endpoint protected. If you add new routes, be aware that they inherit
middleware from the outer app, which exempts `PUBLIC_PATHS`. Routes you add will be
protected by default unless you add their paths to `PUBLIC_PATHS`.

---

## 14. Coolify's service UUID must never change

The UUID `vj5f76xet05bxwdq4utw1kho` appears in:
- Container name
- Volume name  
- Traefik router names
- GitHub secret `COOLIFY_SERVICE_UUID`
- Coolify API calls

If Coolify's service entry is deleted and recreated, it gets a new UUID. Everything
referencing the old UUID — GitHub secret `COOLIFY_SERVICE_UUID`, container names,
and audit volume names — must be updated. Preserve or copy the audit log volume
manually if the old UUID changes.

## 14. GitHub Actions runtime warnings

If GitHub warns that a marketplace action is running on a deprecated Node.js
runtime, bump the affected action versions and rerun the workflow. Keep the deploy
flow itself unchanged.

---

## 16. There is no access control — only identity logging

Any agent with a valid token can do anything. Tokens are for identifying who did
what in the audit log, not for limiting what they can do. There is no way to give
Claude read-only access while giving Roo Code full access, for example.

If you need per-agent permissions in the future, each agent would need to connect to
a different MCP server configured with different tool sets, or the auth middleware
would need to be extended to check agent-specific allowlists per tool.

---

## 17. `WWW-Authenticate` header must be present on every 401

**Discovered 2026-04-11.** Newer MCP clients (Windsurf / Roo Code with MCP
2025-03-26 support) implement OAuth 2.1 discovery. When they receive a 401 response
*without* a `WWW-Authenticate` header, they treat it as an implicit OAuth server and
enter a discovery loop:

```
GET /.well-known/oauth-protected-resource  → 401
GET /.well-known/oauth-authorization-server → 401
POST /register                              → 401
```

After the loop fails, the client surfaces this as `MCP error -32001: Request timed
out` to the user. The actual cause is a reconnection handshake failure, not a
network timeout.

The auth middleware in `server.py` must always return:
```
WWW-Authenticate: Bearer realm="devops-mcp"
```
on every 401 (missing token) and a matching header on every 403 (bad token). This
tells the client to use static Bearer token auth and skip the OAuth flow entirely.

See [troubleshooting.md](troubleshooting.md) for diagnosis and recovery steps.

---

## 18. Roo Code's MCP client has a ~60-second transport timeout

**Discovered 2026-04-11.** Roo Code (and likely Windsurf) has an internal MCP
transport timeout of roughly 60–75 seconds. If `run_command` is given a `timeout`
greater than this and the command actually runs that long, the client cancels the
request and returns `MCP error -32001: Request timed out` — even though the server
eventually completes the command successfully (visible in the audit log with `ok:true`).

The `timeout` parameter in `run_command` controls the *server-side* subprocess
timeout only. It has no effect on the client's transport timeout.

**Rule of thumb:** Keep individual `run_command` calls under ~50 seconds of wall time.
For longer operations, use `nohup` / background execution and poll for completion:

```
run_command("nohup long_operation > /tmp/out.log 2>&1 &")
# later:
run_command("tail -20 /tmp/out.log")
```

See [troubleshooting.md](troubleshooting.md) for more workarounds.

---

## 19. Server-side hangs are NOT the same as the Roo client timeout

**Discovered 2026-05.** It's tempting to assume every `-32001` / "connection
interrupted" is the client-side timeout described in #18. It's not. Four
*server-side* blocking patterns existed and were fixed in commit `a712d08`:

1. **`_run_on_host` used `subprocess.run`** — only the direct bash child got
   SIGKILL on timeout. For `ssh`, `docker`, or any pipeline, the grandchildren
   kept stdout pipes open and the call blocked past `timeout`. Fixed by
   `Popen(start_new_session=True)` + `os.killpg(pgid, SIGKILL)`.
2. **`read_file` materialized the entire file** via `read_text().splitlines()`
   before slicing. Multi-GB logs allocated GBs and stalled the worker thread.
   Fixed by streaming line-by-line with byte cap (default 5 MB, max 50 MB).
3. **`list_directory(recursive=True)` sorted the full tree** before applying
   `max_entries`. On `/host` it walked and held millions of paths. Fixed by
   bounded `islice` + sort of the window only.
4. **Audit-log reads loaded the whole file** on every call. Fixed by
   tail-from-end seek (last 512 KB); `total` becomes an estimate for big logs.

**How to tell which one you're hitting:** the Roo client-timeout case (#18)
leaves a *successful* audit entry behind — `ok: true, duration_ms: 90077`.
A server-side hang leaves no audit entry at all, because the call never
returned. If `view_audit_log` doesn't show the failed call, suspect this.

See [troubleshooting.md](troubleshooting.md) for the four-pattern breakdown
and a `curl` check to verify the fix after deploy.

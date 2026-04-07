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

## 2. Adding a token does NOT require a code push

Tokens are Coolify environment variables, not code. To add or rotate a token:

Coolify UI → DevOps MCP → Environment Variables → add `TOKEN_<NAME>` → Save

Coolify restarts the container with the new env var automatically. No commit needed.

---

## 3. The docker-compose.yml in this repo is the source of truth for container config

Coolify uses `docker-compose.yml` to define volumes, capabilities, mounts, and image.
If you need to change container configuration (e.g. add a volume, change a capability),
edit `docker-compose.yml` and push to `main`. Do not change these things in the
Coolify UI — those changes will be lost on the next git-triggered redeploy.

---

## 4. Routing goes through Cloudflare Tunnel — not Traefik

`mcp.designflow.app` is routed via the `cloudflared` sidecar container, identical
to `ocgate` and `ocmc`. DNS is a proxied CNAME to the tunnel ID, not an A record
to the VPS IP. Traefik/Coolify proxy plays no role in routing public traffic.

If the endpoint returns 503, the issue is almost always the `cloudflared` container,
not Coolify configuration. Check with: `docker logs devops-mcp-cloudflared-1`

---

## 4. The old gemini-mcp service is still on disk

`/etc/systemd/system/gemini-mcp.service` and `/home/ai/gemini-mcp/` still exist.
The service is stopped and disabled. Do not re-enable it — it will conflict with
devops-mcp on port 8765.

The old service ran as the `ai` user with restricted access to `/home/ai`. The new
one runs as root with full host access. They are not compatible.

---

## 5. `write_file` overwrites the entire file

The `write_file` tool replaces the entire file contents. It is not a patch or diff.
If an AI calls `write_file("/etc/nginx/nginx.conf", content)`, it must provide the
complete file content — not just the changed lines.

The `make_backup=True` default saves a timestamped `.bak` file before overwriting.
These backups accumulate in the same directory as the file. Nobody cleans them up.
Over time, directories with frequently-edited files will fill with `.bak` files.

---

## 6. `run_command` output is capped at 60,000 characters

Commands that produce very long output (e.g. `cat large_file`, `docker logs` with
thousands of lines, `find / -name "*.log"`) will be truncated. The response includes
`stdout_truncated: true` when this happens.

For large outputs, either redirect to a file on the host and use `read_file` to page
through it, or use options to limit output (`tail -n 100`, `grep` filters, etc.).

---

## 7. The status page is unauthenticated

`https://mcp.designflow.app/` is publicly readable. It shows:
- Which agent names are registered (but not their tokens)
- Recent activity (what commands were run and by which agent)
- The list of available tools

This is intentional — it's useful for the owner to check without needing a token.
But be aware that anyone on the internet can see the recent audit log entries,
including command arguments. Avoid running commands with secrets in them (passwords
in command-line args, etc.).

---

## 8. nsenter silently fails without `pid: host`

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

## 9. The `cwd` parameter in `run_command` is not fully wired through nsenter

The `run_command` tool accepts a `cwd` parameter. In container mode, the intended
working directory is passed as an env var (`NSENTER_CWD`) but the nsenter command
itself always runs from `/`. The bash command inside nsenter does NOT automatically
`cd` to the requested directory.

If you need a command to run in a specific directory, include the `cd` explicitly:
```
run_command("cd /home/ai/myproject && git status")
```

---

## 10. Double middleware application

In `create_app()`, the auth middleware is applied to both the outer Starlette app
and the inner FastMCP app. This was needed to make the public status page work while
keeping the MCP endpoint protected. If you add new routes, be aware that they inherit
middleware from the outer app, which exempts `PUBLIC_PATHS`. Routes you add will be
protected by default unless you add their paths to `PUBLIC_PATHS`.

---

## 11. Coolify's service UUID must never change

The UUID `vj5f76xet05bxwdq4utw1kho` appears in:
- Container name
- Volume name  
- Traefik router names
- GitHub secret `COOLIFY_SERVICE_UUID`
- Coolify API calls

If Coolify's service entry is deleted and recreated, it gets a new UUID. Everything
referencing the old UUID — the container name, the volume mount in `docker run`,
the Traefik labels — must be updated. The audit log volume with the old UUID name
will no longer be mounted (though it still exists on disk and can be re-mounted
manually).

---

## 12. GitHub Actions Node.js deprecation (deadline: June 2026)

The workflow uses `docker/build-push-action@v6`, `docker/login-action@v3`, and
`docker/setup-buildx-action@v3` which run on Node.js 20. GitHub will force Node.js 24
starting June 2, 2026. Update these to their latest versions before then to avoid
build failures.

---

## 13. There is no access control — only identity logging

Any agent with a valid token can do anything. Tokens are for identifying who did
what in the audit log, not for limiting what they can do. There is no way to give
Claude read-only access while giving Roo Code full access, for example.

If you need per-agent permissions in the future, each agent would need to connect to
a different MCP server configured with different tool sets, or the auth middleware
would need to be extended to check agent-specific allowlists per tool.

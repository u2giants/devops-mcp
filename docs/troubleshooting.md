# Troubleshooting

## `MCP error -32001: Request timed out` in Windsurf / Roo Code

**Symptom:** The IDE shows `Error executing MCP tool: MCP error -32001: Request timed out`
when trying to use any tool. The server logs show a burst of 401s followed by requests
to `/.well-known/oauth-protected-resource` and `POST /register`, all returning 401.

**Root cause:** When the MCP connection drops (e.g. Cloudflare Tunnel hiccup, network
reset, IDE restart), newer versions of Roo Code / Windsurf try to reconnect using the
MCP 2025-03-26 OAuth discovery flow. They send the first request *without* the bearer
token to probe for OAuth support. Without a `WWW-Authenticate` header in the 401
response, the client interprets the error as "OAuth server present but unconfigured"
and enters an OAuth discovery loop — all of which fails with 401. After exhausting the
loop, it returns `-32001` to the user.

**Fix applied (2026-04-11):** The auth middleware now returns
`WWW-Authenticate: Bearer realm="devops-mcp"` on every 401 and 403. This signals
to the client that static Bearer token auth is expected, short-circuiting the OAuth
discovery loop and causing the client to immediately retry with its configured token.

**If you see this error again:**

1. Check the devops-mcp logs for the OAuth probe pattern:
   ```bash
   docker logs devops-mcp --since 5m 2>&1 | grep -E "401|well-known|register"
   ```
   If you see `GET /.well-known/oauth-protected-resource` returning 401, the
   `WWW-Authenticate` header is missing (the container is running old code).

2. Verify the header is present in the 401 response:
   ```bash
   curl -sI -X POST https://mcp.designflow.app/mcp \
     -H "Content-Type: application/json" -d '{}' | grep -i www-authenticate
   # Should print: www-authenticate: Bearer realm="devops-mcp"
   ```

3. If the header is missing, a redeploy picks up the fix:
   ```bash
   # trigger CI/CD via a git push, or restart the running container:
   docker restart devops-mcp
   ```

4. As a short-term workaround (if the server isn't reachable), reload the MCP
   connection in your IDE — Windsurf: Command Palette → "Reload MCP Servers".

---

## `MCP error -32001: Request timed out` during long-running commands

**Symptom:** The IDE shows `-32001: Request timed out` while a `run_command` call is executing
a long-running command (e.g. `sleep 90`, a slow `apt install`, a lengthy `curl`). The server
audit log shows the command eventually completed successfully (`ok: true`), but the client
already gave up.

**Root cause:** Roo Code's MCP transport layer has an internal client-side timeout of roughly
60–75 seconds. When `run_command` is called with `timeout > ~60`, the server dutifully waits
for the process to finish, but Roo's client cancels the in-flight HTTP request before the
response arrives and returns `-32001`.

The server is not broken — the command ran to completion. The error is entirely on the
client side.

**Confirmed occurrence (2026-04-11):**
```
run_command("sleep 90 && curl ...", timeout=120)
→ server: ok=true, duration_ms=90077
→ Roo: -32001 at T+67s (client timed out before server responded)
```

**Workarounds:**

1. **Keep commands under ~60 seconds.** For long operations, split them:
   ```
   # Instead of: sleep 90 && do_thing
   # Step 1: start in background
   run_command("nohup do_thing > /tmp/out.log 2>&1 &")
   # Step 2: poll for completion
   run_command("tail -f /tmp/out.log")
   ```

2. **Use `nohup` / background execution** for fire-and-forget tasks, then check output:
   ```
   run_command("nohup apt-get upgrade -y > /tmp/apt.log 2>&1 &")
   # later:
   run_command("tail -20 /tmp/apt.log")
   ```

3. **Redirect long output to a file** and read it back:
   ```
   run_command("docker build -t myimage . > /tmp/build.log 2>&1; echo done")
   # then:
   read_file("/tmp/build.log")
   ```

**Note:** This is a Roo/Windsurf client limitation. There is no server-side setting to extend
the client's timeout. The `timeout` parameter in `run_command` controls how long the *server*
waits for the subprocess — it does not affect the client's transport timeout.

---

## Server-side hangs — `read_file` on large files, `ssh` / pipeline commands

**Symptom:** Tool call hangs well past its nominal `timeout`, eventually returning `-32001`
or "connection interrupted." Distinct from the Roo client-timeout case above: here the
server itself is genuinely stuck, not just the client giving up.

**Three independent root causes were fixed in `server.py` (commit 2026-05-28):**

### 1. `_run_on_host` killed bash but not its grandchildren

`subprocess.run(..., timeout=N)` sends SIGKILL only to the direct bash child. For commands
that fork — `ssh`, `docker`, any pipeline like `cmd1 | cmd2 | cmd3` — bash exits but its
grandchildren stay alive holding stdout pipes open. `subprocess.run` then blocks on
`communicate()` waiting for those pipes to close, which never happens. The MCP server
appears hung; the audit log shows nothing because the call never returned.

Fixed by switching to `Popen(start_new_session=True)` + `os.killpg(pgid, SIGKILL)` on
timeout. The whole process group dies at once. Verified with `bash -c 'sleep 30 | sleep 30 | cat'`,
`timeout=2`: returns at exactly 2.00s instead of hanging 30s.

Same root cause and fix as the synology-monitor 4-day-runaway `grep -R` incident.

### 2. `read_file` materialized the entire file before slicing

`p.read_text(...).splitlines()[offset:offset+limit]` loads every byte of the file into
memory and then throws most of it away. On a multi-GB log this allocates GBs, blocks the
worker thread for many seconds, and risks OOM-killing the container. Clients see a hang.

Fixed by streaming line-by-line and breaking out as soon as the window is filled OR
`max_bytes` (default 5MB, hard cap 50MB) is scanned. For files larger than `max_bytes`,
the response includes `truncated_by_bytes: true` and `total_lines` is omitted — use a
higher `offset`, raise `max_bytes`, or shell out via `run_command("tail -n 1000 …")`.

### 3. `list_directory(recursive=True)` sorted the full tree before truncating

`sorted(p.rglob("*"), …)` materialized every entry under the path into memory before
applying `max_entries=200`. On `/host` that walked and held millions of paths.

Fixed by streaming `rglob` through `itertools.islice` to bound at `max_entries + 1`
entries, then sorting only the bounded window. Truncation is reported honestly via
the `truncated` boolean.

### Bonus: audit log reads no longer load the full log

`view_audit_log` and the status page used to call `Path(AUDIT_LOG_PATH).read_text(...)`
on every invocation. As the audit log grows this got slower without bound and could
block the worker thread on a busy server.

Fixed by `_tail_audit_lines()` which seeks to the last 512KB of the file. For audit
logs larger than that, the `total` field becomes an estimate from the bytes-per-line
average and the response is marked `total_is_estimate: true`.

### How to confirm in production

After the next deploy, run:

```bash
# Should return in ~2s, not ~30s:
curl -s -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run_command","arguments":{"command":"sleep 30 | sleep 30 | cat","timeout":2}}}' \
  https://mcp.designflow.app/mcp

# read_file on a multi-MB log file should now return quickly without OOM:
docker logs devops-mcp --since 5m 2>&1 | grep -E "MemoryError|Killed|read_file"
```

---

## Cloudflare 502 / 503 errors

**Symptom:** Browser or AI client gets `502 Bad Gateway` or `503 Service Unavailable` from Cloudflare.

**This is an infrastructure problem, not a token or auth issue.** A Cloudflare 502 means the Cloudflare Tunnel cannot reach the backend container. The token could be perfectly valid — the request never gets that far.

**What to check:**

1. **Is the cloudflared sidecar running?**
   ```bash
   docker ps | grep cloudflared
   ```
   If it's not running, the tunnel is down. Restart it:
   ```bash
   docker compose up -d cloudflared
   ```

2. **Is the devops-mcp container running?**
   ```bash
   docker ps | grep devops-mcp
   ```
   If the container is down, the tunnel has nothing to forward to.

3. **Check cloudflared logs:**
   ```bash
   docker logs devops-mcp-cloudflared-1 2>&1 | tail -30
   ```
   Look for connection refused, timeout, or tunnel registration errors.

4. **Can you reach the container directly?**
   ```bash
   curl -s http://localhost:8765/
   ```
   If this works but the public URL returns 502, the tunnel is the problem.
   If this also fails, the container itself is the problem.

**Common causes:**
- Container was restarted by Coolify but the cloudflared sidecar lost its connection
- Docker network issue between cloudflared and the MCP container
- Cloudflare Tunnel token expired or was revoked in the Cloudflare dashboard

---

## Quick health check

```bash
# Is the container running?
docker ps --filter name=devops-mcp

# Is the server responding?
curl -s https://mcp.designflow.app/
# Should return an HTML page

# Is auth working?
curl -s https://mcp.designflow.app/mcp -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"health","arguments":{}}}'
# Should return JSON with "server":"devops-mcp"
```

---

## Container won't start

**Symptom:** `docker ps` shows no devops-mcp container, or it shows `Exited`.

**Check logs:**
```bash
docker logs devops-mcp-vj5f76xet05bxwdq4utw1kho 2>&1 | tail -30
```

**Common causes:**

1. **Port conflict.** Port 8765 might be in use.
   ```bash
   ss -tlnp | grep 8765
   ```
   The old `gemini-mcp` systemd service used port 8765. If it was accidentally
   re-enabled, stop it:
   ```bash
   sudo systemctl stop gemini-mcp && sudo systemctl disable gemini-mcp
   ```

2. **Missing GHCR image.** The image `ghcr.io/u2giants/devops-mcp:main` doesn't
   exist locally and Docker can't pull it.
   ```bash
   echo "<github_token>" | docker login ghcr.io -u u2giants --password-stdin
   docker pull ghcr.io/u2giants/devops-mcp:main
   ```

3. **Network doesn't exist.** The `coolify` Docker network was removed.
   ```bash
   docker network ls | grep coolify
   # If missing, Coolify recreates it on restart, or:
   docker network create coolify
   ```

---

## HTTPS not working / SSL error

**Symptom:** Browser shows certificate error or connection refused on port 443.

1. **Check Traefik is running:**
   ```bash
   docker ps --filter name=coolify-proxy
   ```

2. **Check Traefik picked up the container's labels:**
   ```bash
   # Traefik dashboard (if enabled) at http://178.156.180.212:8080
   # Or check Traefik logs:
   docker logs coolify-proxy 2>&1 | grep -i "mcp\|designflow" | tail -20
   ```

3. **Check the container is on the coolify network:**
   ```bash
   docker inspect devops-mcp-vj5f76xet05bxwdq4utw1kho \
     --format '{{json .NetworkSettings.Networks}}' | python3 -m json.tool
   # Should show "coolify" network with an IP address
   ```

4. **Let's Encrypt rate limit.** If you've been recreating the container and
   requesting new certificates repeatedly, Let's Encrypt may have rate-limited you.
   Wait and try again. The certificate is cached in Traefik's volume once issued.

---

## Commands running inside container instead of on host

**Symptom:** `run_command("systemctl status nginx")` returns "command not found"
or refers to container internals.

**Diagnosis:**
```bash
# Check if IN_CONTAINER is being detected correctly
curl ... -d '{"method":"tools/call","params":{"name":"health","arguments":{}}}' | grep in_container
# Should be true
```

**Causes:**
- Container started without `--pid host` — nsenter can't reach host PID 1
- Container started without `--privileged` — nsenter is denied permission

Re-run the full `docker run` command from [deployment.md](deployment.md) with all flags.

---

## File operations affecting wrong path

**Symptom:** `read_file("/etc/nginx/nginx.conf")` returns "not found" even though
the file exists on the host.

**Check:** The container's `/host` mount.
```bash
docker exec devops-mcp-vj5f76xet05bxwdq4utw1kho ls /host/etc/nginx/
```
If this fails, the `/:/host` volume isn't mounted. Re-run the `docker run` command.

---

## Audit log not recording

**Symptom:** `view_audit_log` returns empty, or the status page shows no activity.

**Check:**
```bash
docker exec devops-mcp-vj5f76xet05bxwdq4utw1kho ls -la /audit/
```

If `/audit` is empty or doesn't exist:
- The volume may not be mounted. Check `docker inspect` for volume mounts.
- The container may not have write permission. Check container logs for errors.

**Check the volume exists:**
```bash
docker volume ls | grep mcp-audit
```
Should show `vj5f76xet05bxwdq4utw1kho_mcp-audit`. If missing, the volume was deleted
— audit history for the period it was missing is permanently lost.

---

## Token not working

**Symptom:** Getting 403 "Invalid token" with a token you just added.

Tokens are loaded at container startup only. Adding a new `TOKEN_*` env var to
Coolify does not take effect until the container is restarted with that env var
in the `docker run` command. Simply restarting via Coolify UI is not enough —
you must re-run the full `docker run` command with the new token included.

---

## Status page shows stale data / doesn't refresh

The status page has a 30-second meta-refresh. If it's not updating, the container
may be returning a cached response. Try a hard browser refresh (Ctrl+Shift+R / Cmd+Shift+R).

The status page reads the audit log file on every page load — there is no server-side
caching.

---

## CI built successfully but site didn't update

GitHub Actions pushes a new image to GHCR and calls the Coolify restart API. The
Coolify restart restarts the *existing* container — it does not pull the new image.

To actually deploy the new image:
```bash
docker pull ghcr.io/u2giants/devops-mcp:main
# then re-run the full docker run command
```

See [cicd.md](cicd.md) for full explanation.

---

## Container appears in Coolify but shows wrong status

Coolify shows the status it last knew about, which may lag. Its "restart" button
will restart the existing container (not pull new image). Use the Coolify UI for
visibility only — use `docker ps` and the `docker run` command for actual management.

---

## Recovering from complete container loss

If the container is gone and needs to be rebuilt from scratch:

1. Make sure the GHCR image is available (or rebuild it):
   ```bash
   docker pull ghcr.io/u2giants/devops-mcp:main
   # or: cd /home/ai/devops-mcp && docker build -t ghcr.io/u2giants/devops-mcp:main .
   ```

2. Make sure the `coolify` network exists:
   ```bash
   docker network create coolify 2>/dev/null || true
   ```

3. Re-run the full `docker run` command from [deployment.md](deployment.md).

4. Verify with `curl https://mcp.designflow.app/`.

The audit log volume (`vj5f76xet05bxwdq4utw1kho_mcp-audit`) survives container loss
as long as it wasn't explicitly deleted. Historical logs will be available again once
the new container mounts the same volume.

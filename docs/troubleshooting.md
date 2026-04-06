# Troubleshooting

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
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer wl6Uxf9dlZ981eNF_d8M7EQXbkI56fvtZV-5i0nWa0k" \
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

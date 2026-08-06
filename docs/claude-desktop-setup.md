# Claude Desktop & Windows Setup

Connect Claude desktop (Cowork mode) to devops-mcp and synology-monitor on any Windows PC.

## How the connection works

Both servers are **remote MCP servers** — they run in Docker containers on the VPS, not on your Windows machine. Your PC only needs Node.js (for `npx`) and two entries in `claude_desktop_config.json`.

The Claude desktop app uses the `mcp-remote` npm package as a local bridge. It connects to the server URLs over HTTPS, authenticating with a bearer token. Nothing else runs locally.

---

## One-time setup on a new Windows PC

**Step 1 — Install Node.js.** Download and install the LTS release from [nodejs.org](https://nodejs.org). Accept all defaults. Verify: open a new PowerShell window and type `node --version`.

**Step 2 — Install Claude desktop.** Download from [claude.ai](https://claude.ai) and sign in. Do this before running the script so the config folder exists.

**Step 3 — Run the setup script.** Save the script below as `setup-claude-mcps.ps1` and run it in PowerShell. The script safely merges the MCP entries into your existing config without overwriting anything else (preferences, Chrome pairing, other MCPs).

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned   # first time only
.\setup-claude-mcps.ps1
```

**Step 4 — Restart Claude desktop.** Fully quit and reopen. The MCPs will connect on startup.

---

## Setup script

Save as `setup-claude-mcps.ps1`. Fill in the actual token values before running (see [tokens.md](tokens.md)).

```powershell
# Claude Desktop MCP Setup
# Merges devops-mcp and synology-monitor into existing claude_desktop_config.json.
# Safe to run on a machine that already has Claude configured.

$configPath = "$env:APPDATA\Claude\claude_desktop_config.json"
New-Item -ItemType Directory -Force -Path "$env:APPDATA\Claude" | Out-Null

if (Test-Path $configPath) {
    $config = Get-Content $configPath -Raw | ConvertFrom-Json
    Write-Host "Found existing config, merging..."
} else {
    $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
    Write-Host "No config found, creating..."
}

if (-not $config.mcpServers) {
    $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
}

# devops-mcp: full VPS access via Streamable HTTP
# Note: mcp-remote auto-detects Streamable HTTP - no --transport flag needed
$config.mcpServers | Add-Member -NotePropertyName "devops-mcp" -NotePropertyValue ([PSCustomObject]@{
    command = "C:\PROGRA~1\nodejs\npx.cmd"
    args = @(
        "-y", "mcp-remote@0.1.38",
        "https://mcp.designflow.app/mcp",
        "--header", "Authorization: Bearer REPLACE_WITH_TOKEN_ROOCODE"
    )
}) -Force

# synology-monitor: NAS monitoring via Streamable HTTP
$config.mcpServers | Add-Member -NotePropertyName "synology-monitor" -NotePropertyValue ([PSCustomObject]@{
    command = "C:\PROGRA~1\nodejs\npx.cmd"
    args = @(
        "-y", "mcp-remote@0.1.38",
        "https://nas-mcp.designflow.app/mcp",
        "--transport", "http",
        "--header", "Authorization: Bearer REPLACE_WITH_NAS_BEARER_TOKEN"
    )
}) -Force

$config | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8
Write-Host "Done. Restart Claude desktop to activate the MCPs."
```

**Keep the filled-in version of this script private.** Do not commit it to a public repo.

---

## What each MCP gives you

| MCP | What Claude can do |
|---|---|
| `devops-mcp` | Run any shell command on the VPS, manage Docker containers, read/write files, view audit logs |
| `synology-monitor` | Monitor both NAS units — disk health, SMART tests, backups, network, Btrfs scrubs, logs, repairs |

---

## Critical: transport flags

`mcp-remote` should use Streamable HTTP for both hosted MCP servers.

| Server | Transport | Flag needed |
|---|---|---|
| devops-mcp (`/mcp`) | Streamable HTTP | None — auto-detected correctly |
| synology-monitor (`/mcp`) | Streamable HTTP | `--transport http` |

If a client still points at Synology's old `/sse` URL, update it to `/mcp`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `npx` not found when Claude starts | Node.js not installed, or installed after Claude was opened — restart Claude |
| `npx.cmd` path wrong | Run `where npx` in PowerShell to find the real path and update the script |
| MCP shows connected but tools fail | Token is wrong — verify against `TOKEN_ROOCODE` in Coolify env vars |
| `Set-ExecutionPolicy` refused | Run PowerShell as Administrator |
| synology-monitor fails with 503 | Client may still be using an old `/sse` URL; use `/mcp` |
| Want to verify devops-mcp | Ask Claude: *"call the health tool"* — returns server info if working |
| Want to see connection errors | Check `%APPDATA%\Claude\logs\mcp-server-<name>.log` |

See [troubleshooting.md](troubleshooting.md) for infrastructure-level problems (502s, tunnel down, container not running).

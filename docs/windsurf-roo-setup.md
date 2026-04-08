# Windsurf & Roo Code Setup

Both clients connect via **Streamable HTTP** at `/mcp`. The SSE transport is not used.

## Windsurf configuration

Add this to your Windsurf `mcp_config.json` (usually at `~/.codeium/windsurf/mcp_config.json`):

```json
{
  "mcpServers": {
    "devops-mcp": {
      "serverUrl": "https://mcp.designflow.app/mcp?token=YOUR_TOKEN_HERE"
    }
  }
}
```

Replace `YOUR_TOKEN_HERE` with your agent token from [docs/tokens.md](tokens.md).

## Roo Code configuration

- Transport: HTTP
- URL: `https://mcp.designflow.app/mcp`
- Header: `Authorization: Bearer YOUR_TOKEN_HERE`

Alternatively, you can use query-param auth by appending `?token=YOUR_TOKEN_HERE` to the URL instead of setting a header.

## Verify it works

After configuring either client, verify the connection works before relying on it:

### Quick verification (curl)

```bash
# Test the endpoint with your token
curl -s https://mcp.designflow.app/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

A successful response will include `"result"` with server info. If you get:
- **200 OK** with JSON → working
- **401/403** → token is wrong or missing
- **502/503** → infrastructure problem (see [troubleshooting.md](troubleshooting.md))

### In-client verification

1. Open Windsurf or Roo Code
2. Ask the AI: *"call the health tool"*
3. If it returns server info (container ID, tools list, agents) → connected
4. If it says "tool not found" or "connection failed" → check config

### Troubleshooting table

| Symptom | Likely cause | Fix |
|---|---|---|
| "Connection refused" | Wrong URL or server down | Check `https://mcp.designflow.app/` in browser |
| 401/403 | Token missing or wrong | Verify token matches `TOKEN_<NAME>` in Coolify |
| 502 Bad Gateway | Cloudflare Tunnel can't reach container | See [troubleshooting.md](troubleshooting.md) — infra problem |
| 503 Service Unavailable | Tunnel or container down | Same as 502 |
| Tools don't appear in client | Config not saved, or wrong path | Re-check `mcp_config.json` syntax |
| "SSE" errors in logs | Client trying old SSE transport | Make sure URL ends in `/mcp`, not `/sse` |

## Security note

When using query-parameter auth, the token is visible in the URL. That is acceptable here because the connection is HTTPS-encrypted, but it may still appear in browser history or proxy logs if URL logging is enabled.

Use the header-based HTTP method whenever your client supports it and you want to avoid putting the token in the URL.

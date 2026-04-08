# Windsurf & Roo Code Setup

## Windsurf configuration

Add this to your Windsurf `mcp_config.json` (usually at `~/.codeium/windsurf/mcp_config.json`):

```json
{
  "mcpServers": {
    "devops-mcp": {
      "serverUrl": "https://mcp.designflow.app/sse/sse?token=YOUR_TOKEN_HERE"
    }
  }
}
```

Replace `YOUR_TOKEN_HERE` with your agent token from [docs/tokens.md](tokens.md).

## Roo Code configuration

Roo Code supports both SSE and HTTP transports.

### Option A: SSE (recommended)

- Transport: SSE
- URL: `https://mcp.designflow.app/sse/sse?token=YOUR_TOKEN_HERE`

### Option B: HTTP with header

- Transport: HTTP
- URL: `https://mcp.designflow.app/mcp`
- Header: `Authorization: Bearer YOUR_TOKEN_HERE`

## Security note

When using query-parameter auth, the token is visible in the URL. That is acceptable here because the connection is HTTPS-encrypted, but it may still appear in browser history or proxy logs if URL logging is enabled.

Use the header-based HTTP method whenever your client supports it and you want to avoid putting the token in the URL.

# Hosting Specification

Deployment contract for the FastMCP server. Covers Render configuration, environment variables, endpoints, Dockerfile, and the ngrok fallback. Derived from [ADR 004](../adr/adr_004_hosting_strategy.md).

The server uses **Streamable HTTP** transport (not SSE). Streamable HTTP is the current MCP spec standard -- SSE was deprecated in March 2025. Streamable HTTP uses standard request-response semantics, which eliminates long-lived connection timeout concerns and makes the server compatible with any hosting platform.

## Render Service Configuration

| Setting | Value |
|---------|-------|
| **Service type** | Web Service |
| **Environment** | Docker |
| **Branch** | `josh-fastmcp` |
| **Region** | Oregon (US West) -- closest to GCP Neo4j Aura |
| **Plan** | Free (750 hrs/month, 100 GB bandwidth) |
| **Instance count** | 1 |
| **Health check path** | `/health` |
| **Auto-deploy** | Yes (on push to branch) |

### Build

Render builds from the repo's `Dockerfile`. No `render.yaml` blueprint needed for a single service -- configure via the Render dashboard.

```
Root directory: /          (repo root)
Dockerfile path: Dockerfile
Docker build context: .
```

### Start Command

The Dockerfile's `CMD` handles startup. No override needed in Render. The server must bind to `0.0.0.0` on the port Render assigns via the `PORT` environment variable.

```python
import os

port = int(os.environ.get("PORT", 8000))
mcp.run(transport="http", host="0.0.0.0", port=port)
```

Render sets `PORT` automatically. Local development defaults to `8000`.

## Dockerfile

Minimum viable Dockerfile for the FastMCP server:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "server.py"]
```

Notes:
- Use `python:3.12-slim` to keep the image small and build fast on Render's free tier.
- `server.py` reads `PORT` from the environment (see Start Command above).
- No multi-stage build needed -- the app is pure Python with no compiled assets.

## Environment Variables

Set all environment variables in the Render dashboard under the service's "Environment" tab. Never commit secrets to the repo.

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | HTTP port (set automatically by Render) | `8000` |
| `USE_MOCK_DB` | `true` to use in-memory mock, `false` for Neo4j | `true` |

### Neo4j (required when `USE_MOCK_DB=false`)

| Variable | Description |
|----------|-------------|
| `NEO4J_URI` | Bolt URI, e.g. `neo4j+s://<id>.databases.neo4j.io` |
| `NEO4J_USER` | Database username |
| `NEO4J_PASSWORD` | Database password |

### LLM (required for Create/Update tools)

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `PYTHON_ENV` | `development` or `production` | `production` |

## Endpoints

The MCP server exposes two categories of endpoints: MCP transport and operational.

### MCP Transport

| Path | Method | Description |
|------|--------|-------------|
| `/mcp` | POST | Streamable HTTP transport endpoint. MCP clients connect here. Standard request-response -- no long-lived connections. |

This is the URL teammates and external agents use to connect:

```
https://<service-name>.onrender.com/mcp
```

### Operational

| Path | Method | Description |
|------|--------|-------------|
| `/health` | GET | Returns `200` if the server is up. Render pings this for health checks. Should verify DB connectivity when `USE_MOCK_DB=false`. |

### MCP Tools (exposed via Streamable HTTP transport)

These are not REST endpoints -- they are MCP tool calls routed through the `/mcp` transport. Listed here for completeness. See [mcp_tools_spec.md](mcp_tools_spec.md) for request/response schemas.

| Tool | Description |
|------|-------------|
| `search_skills` | Query skills via hybrid search |
| `create_skill` | Extract a new skill from a conversation |
| `update_skill` | Refine an existing skill with new data |

## Free Tier Sleep Behavior

Render's free tier puts the service to sleep after 15 minutes of inactivity. First request after sleep takes 30-60 seconds (cold start: Docker container restart).

Mitigations for demo day:
1. **Manual wake**: Hit the `/health` endpoint 1-2 minutes before presenting.
2. **Cron ping** (optional): Use an external cron service to ping `/health` every 14 minutes. Only needed if the demo window is unpredictable.

Do not use the cron approach long-term on the free tier -- Render may flag it as abuse.

## Deployment Workflow

### First Deploy

1. Create a Render account (no credit card required).
2. Create a new **Web Service** from the GitHub repo.
3. Set the branch to `josh-fastmcp`.
4. Set environment to **Docker**.
5. Add environment variables: `USE_MOCK_DB=true`.
6. Deploy. Render builds the Docker image and starts the service.
7. Copy the public URL and share with teammates:
   ```
   https://<service-name>.onrender.com/mcp
   ```

### Subsequent Deploys

Push to `josh-fastmcp`. Render auto-deploys on push.

### Switching to Real Neo4j

No code changes. In the Render dashboard:

1. Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.
2. Set `USE_MOCK_DB=false`.
3. Save. Render redeploys automatically.

## ngrok Fallback

If Render is down or broken on demo day, use ngrok to expose the local server.

### Setup

```bash
# One-time setup
brew install ngrok
ngrok authtoken <your-token>
```

### Run

```bash
# Terminal 1: start server
USE_MOCK_DB=true python server.py

# Terminal 2: expose it
ngrok http 8000
```

ngrok outputs a public HTTPS URL. Share the `/mcp` path:

```
https://<random>.ngrok-free.app/mcp
```

### Limitations

- Laptop must stay open and connected to the internet.
- Free tier URL changes every time ngrok restarts.
- Free tier shows a browser interstitial page on first visit (should not affect MCP HTTP connections).

## Connection Reference

Quick-reference for teammates connecting MCP clients to the server:

```
# Render (primary)
https://<service-name>.onrender.com/mcp

# ngrok (fallback)
https://<random>.ngrok-free.app/mcp

# Local development
http://localhost:8000/mcp
```

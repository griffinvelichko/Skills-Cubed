# ADR 004: Hosting Strategy -- Render (Primary) + ngrok (Fallback)

**Status**: Proposed
**Date**: 2026-02-05
**Context**: Hackathon hosting decision. Need a public HTTPS URL for the MCP server so teammates and demo audience can connect from any network.

## Decision

Deploy the FastMCP server to **Render** as the primary hosting platform. Use **ngrok** (local tunnel) as a day-of fallback if Render has issues. Optionally try **Prefect Horizon** (FastMCP Cloud) as a zero-config experiment, but do not depend on it.

## Why Render

### SSE Compatibility

The MCP server uses SSE (Server-Sent Events) transport, which keeps long-lived HTTP connections open. Most platforms kill these connections after 30-60 seconds. Render allows **up to 100-minute request duration** -- the most generous timeout of any platform evaluated. No special configuration needed.

### Persistent Process (Not Serverless)

ADR 001 rejected serverless due to cold starts and the need for persistent Neo4j connections. Render runs a persistent container process -- the server stays up and Neo4j Bolt connections remain pooled. No per-request spin-up.

### No Outbound Port Restrictions

Neo4j Aura on GCP (ADR 002) uses the Bolt protocol on port 7687. Some platforms (e.g., Hugging Face Spaces) restrict outbound traffic to ports 80/443/8080. Render has no outbound port restrictions -- Bolt connections to Neo4j will work without proxying.

### Branch Deployment

The server code lives on `josh-fastmcp` branch. Render can deploy from any branch. Prefect Horizon only auto-deploys from `main` or PR preview URLs.

### Environment Variables

Full dashboard support for env vars. Easy to start with `USE_MOCK_DB=true` and swap to Neo4j credentials (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) when Torrin has the database ready. No code changes needed -- just update env vars and Render redeploys.

### Dockerfile Support

Render builds from the existing Dockerfile in the repo. No changes to the build configuration needed.

## Free Tier

- No credit card required
- 750 hours/month, 100 GB bandwidth
- **Sleeps after 15 minutes of inactivity** -- cold start takes 30-60 seconds on wake
- Paid tier ($7/month) eliminates sleep, but free tier is sufficient for hackathon demo

The sleep behavior is manageable: hit the URL a minute before presenting, or set up a cron ping.

## Platforms Evaluated

| Platform | SSE Timeout | Persistent Process | Outbound Ports | Free Tier | Why Not Primary |
|----------|-------------|-------------------|----------------|-----------|-----------------|
| **Render** | 100 min | Yes | Unrestricted | Yes (sleeps) | -- (chosen) |
| **Prefect Horizon** | Native | Yes | Unknown | Free beta | Branch limitation, immature env var docs |
| **Railway** | **5 min hard limit** | Yes | Unrestricted | $5 trial only | SSE timeout kills connections every 5 min |
| **Google Cloud Run** | 60 min (configurable) | Serverless (scales to zero) | Unrestricted | Generous | Serverless rejected by ADR 001; complex IAM setup |
| **Fly.io** | No limit | Yes (full VM) | Unrestricted | Limited | Requires credit card, MCP tooling is experimental |
| **Cloudflare Workers** | 100s idle limit | No (edge functions) | N/A | Generous | Requires keepalive heartbeats, Python support immature |
| **Hugging Face Spaces** | Undocumented | Yes | **80/443/8080 only** | Yes (sleeps 48h) | Port restrictions block Neo4j Bolt |
| **Google Cloud Run (warm)** | 60 min | Yes (`min-instances=1`) | Unrestricted | Costs money | Overkill for hackathon; complex setup |

## Platforms Explicitly Rejected

| Platform | Issue |
|----------|-------|
| **Serverless (Cloud Functions, Lambda)** | Cold starts, no persistent connections (ADR 001) |
| **Railway** | 5-minute hard SSE timeout, no permanent free tier |
| **Cloudflare Workers** | 100-second idle timeout, Python support immature |

## SSE vs Streamable HTTP

SSE is deprecated in the MCP spec (March 2025) in favor of Streamable HTTP. FastMCP supports both -- switching is a one-line change:

```python
# SSE (current):
mcp.run(transport="sse", host="0.0.0.0", port=8000)

# Streamable HTTP (future):
mcp.run(transport="http", host="0.0.0.0", port=8000)
```

Streamable HTTP uses standard request-response instead of long-lived connections, which eliminates most platform timeout concerns. We should consider switching transport before production, but SSE works fine on Render for the hackathon demo.

## Fallback: ngrok

If Render has issues day-of:

```bash
# Terminal 1
USE_MOCK_DB=true python server.py

# Terminal 2
ngrok http 8000
```

Public HTTPS URL in seconds. Already tested and documented in `docs/hosting-plan.md`. Limitation: laptop must stay open.

## Integration Path

All steps are env-var-only changes -- no code modifications needed:

1. **Demo day**: Deploy to Render with `USE_MOCK_DB=true`. Share HTTPS URL with teammates.
2. **Neo4j ready**: Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` in Render dashboard. Set `USE_MOCK_DB=false`. Render auto-redeploys.
3. **Griffin connects**: Orchestration layer points at `https://<render-url>/sse`.
4. **Torrin tests**: Evaluation harness hits the same endpoint.

## Consequences

- Josh deploys to Render and shares the public URL with Torrin and Griffin
- All teammates can test against the live endpoint from any network
- Switching from mock DB to real Neo4j is a dashboard env var change, not a code change
- If we outgrow the free tier or need zero-downtime, upgrade to Render paid ($7/month) or migrate to Cloud Run
- ngrok remains as a tested fallback that requires zero platform setup

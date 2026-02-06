# ADR 001: MCP Architecture — FastMCP Server with 3 Tools

**Status**: Accepted (updated 2026-02-05)
**Date**: 2026-02-05
**Context**: Hackathon architecture decision, updated after research sprint

## Decision

Build a FastMCP-based server that exposes exactly 3 tools: `search_skills`, `create_skill`, `update_skill`. Skills are executable `.md` playbooks (Do/Check/Say action steps), not knowledge articles. The search tool uses Gemini Flash as a judge to return one matching playbook or nothing — no threshold-based scoring.

## Why FastMCP

- **Protocol-native**: FastMCP handles all MCP protocol boilerplate — JSON-RPC framing, capability negotiation, tool discovery, session management. We write tool handlers, not protocol code.
- **Decorator-based**: `@mcp.tool()` with type hints and docstrings auto-generates tool definitions (name, description, inputSchema). No manual JSON Schema.
- **Transport-agnostic**: Same tool code works over stdio (local dev, Claude Desktop) and Streamable HTTP (hosted demo). Switch with one argument.
- **FastAPI underneath**: FastMCP uses FastAPI internally. We get async, Pydantic validation, and can add non-MCP endpoints (health checks, admin) alongside.

## Why Exactly 3 Tools

The product is a learning loop: **search** for an existing playbook, **create** a new playbook from a successful resolution, **update** a playbook when the agent had to deviate. Every other feature is downstream.

## Tool Routing

```
Agent (Fin/Claude) → MCP Server (FastMCP)
  └── tools/call "search_skills"
        → Neo4j hybrid search → top candidates
        → Flash judge: "Does any playbook solve this?" → ONE skill or NONE
        → Agent executes playbook or reasons from scratch

  └── tools/call "create_skill"  (post-conversation)
        → Gemini Pro extracts .md playbook from transcript
        → db.check_duplicate → Neo4j write → return skill

  └── tools/call "update_skill"  (post-conversation)
        → db.get_skill → Gemini Pro refines .md → Neo4j update → return changes
```

## Alternatives Considered

| Option | Why Rejected |
|--------|-------------|
| LangChain/LangGraph | Too much abstraction for 3 tools. Framework overhead > value. |
| Raw FastAPI (no FastMCP) | Works but requires manual JSON-RPC, capability negotiation, tool discovery. FastMCP handles all of this. |
| gRPC | Team less familiar. Overkill for a hackathon demo. |
| Serverless (Cloud Functions) | Cold starts hurt the demo. Need persistent Neo4j connections. |
| Threshold-based routing (no LLM judge) | Retrieval scores aren't calibrated. Magic numbers require per-domain tuning. Flash judge makes semantic decisions. |

## Consequences

- Josh owns FastMCP server setup (`src/server/`), transport config, hosting
- Griffin owns tool handler logic (`src/orchestration/`), Flash judge prompt, Pro extraction/refinement prompts
- Torrin owns Neo4j queries called by the handlers (`src/db/`, `src/skills/`)
- Tools are discoverable via `tools/list` — any MCP client auto-integrates
- Adding a 4th tool is one `@mcp.tool()` decorator

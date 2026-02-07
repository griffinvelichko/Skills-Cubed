# Devpost Submission

## Project Name
Skills Cubed

## Elevator Pitch
Autonomously create and update domain specific skills for your agents to save context and time.

## Built With
Python, FastAPI, FastMCP, Neo4j, Google Gemini, Google Agent Development Kit (ADK), Render, Lovable, Pydantic, Docker, Pytest, Matplotlib

## Try It Out Links
- https://github.com/Skills-Cubed/Skills-Cubed
- https://github.com/Skills-Cubed/Skills-Google-ADK-Agent

---

## About the Project

## Inspiration

Customer support AI has a cold start problem. Every time an agent encounters a new issue, it reasons from scratch — burning expensive LLM tokens and making the customer wait. The next time someone asks the exact same question, it does it all over again. Humans don't work this way. A support rep who solves a tricky billing dispute on Monday doesn't re-derive the solution on Tuesday — they remember what worked.

We asked: what if an AI agent could do the same? Not just retrieve documents from a static knowledge base, but *write its own playbooks* from successful interactions, and get measurably better with every conversation.

## What it does

Skills Cubed is a **continual-learning MCP server** that any AI agent can connect to. It exposes three tools via the Model Context Protocol:

- **Search Skills** — Hybrid vector + keyword search over learned resolution playbooks. A Gemini Flash judge selects the best match semantically, not by arbitrary score threshold.
- **Create Skill** — After a successful resolution, extracts a structured playbook (with Do/Check/Say action steps) from the conversation transcript.
- **Update Skill** — When an agent deviates from an existing playbook and succeeds, refines the skill with the new approach.

The key insight: **skills created from conversation N are immediately searchable for conversation N+1.** There's no batch retraining, no reindexing pipeline. Neo4j auto-indexes on write, so knowledge becomes available in seconds.

The system tells a story in three beats:
1. **No skills** — Agent reasons from scratch using Gemini. Slow, expensive.
2. **First encounter** — Agent resolves a complex issue, creates a skill from it.
3. **Next similar query** — Skill found instantly, Flash serves it. Fast, cheap, and the resolution quality improves because the playbook captures proven steps.

## How we built it

### Architecture

```
[Any MCP Client] → [Skills Cubed MCP Server] → [Neo4j (Hybrid Search)]
       ↑                    ↓                         ↑
       └──── resolution ←── Gemini Flash/Pro ──── skill CRUD
```

**MCP Server** — Built with [FastMCP](https://github.com/jlowin/fastmcp) on FastAPI. Streamable HTTP transport, hosted on **Render**. Three tool handlers map directly to orchestration functions. Render gives us persistent containers (no serverless cold starts), 100-minute request timeouts for SSE compatibility, and unrestricted outbound ports for Neo4j Bolt connections.

**Database** — **Neo4j Aura** on GCP. Dual indexes: a 768-dimensional cosine vector index for semantic similarity and a BM25 fulltext index for keyword matching. Hybrid search merges both (0.7 vector + 0.3 keyword), with min-max normalization on BM25 scores. No re-indexing on updates — skills are searchable the moment they're written.

**LLM Layer** — **Google Gemini** powers everything:
- *Gemini Flash* — Judge calls (routing queries to skills), resolution generation, evaluation
- *Gemini Pro* — Skill extraction from conversations, skill refinement
- *Gemini Embedding (gemini-embedding-001)* — 768-dim vectors for semantic search, L2-normalized at reduced dimensionality

The two-tier strategy means cost drops over time: as skills accumulate, Flash handles more queries and Pro is called less frequently.

**Google ADK Agent** — We built a baseline agent using the **Google Agent Development Kit** ([Skills-Google-ADK-Agent](https://github.com/Skills-Cubed/Skills-Google-ADK-Agent)) powered by Gemini 2.0 Flash. This serves as the consumer side — an MCP client that connects to our server and uses the three tools to handle customer conversations. The ADK framework handles session management, tool routing, and agent lifecycle.

**Console UI** — Built with **Lovable** ([skills-cubed-console](https://github.com/Skills-Cubed/skills-cubed-console)) to provide a visual interface for browsing the skills knowledge base, monitoring skill growth, and observing the agent's learning progress.

### Evaluation Harness

We built a rigorous evaluation pipeline to prove the system actually works — not just demo-ware. Using the [ABCD dataset](https://github.com/asappresearch/abcd) (10K+ human-to-human customer service dialogues, 55 intent types), we run two phases on the same conversations:

1. **Baseline** — Gemini resolves each conversation with *no* skill access. An LLM judge scores quality (1-5) against the human agent's ground truth resolution.
2. **Continual Learning** — Same conversations, but now the agent searches for skills, creates new ones, and uses existing ones. Skills accumulate as it goes.

The result is an **improvement curve** — and this is the heart of the entire project. Judge scores start at baseline (what Gemini can do on its own with zero learned knowledge) and rise as skills accumulate. Early conversations look identical to baseline because no skills exist yet. But as the agent resolves issues and writes playbooks, later conversations benefit from that accumulated knowledge. The curve bends upward.

This is the core metric — not latency, not cache hit rate, but **actual resolution quality as scored by an independent judge against human expert ground truth.** We're not measuring whether the system is fast (it is). We're measuring whether it makes the agent *better at its job* over time. That's the thesis: a self-reinforcing loop where every successful interaction makes the next one more likely to succeed.

### Team

Three developers, each running their own Claude Code instance on a shared repo with frozen interface contracts:

| Developer | Domain | Key Modules |
|-----------|--------|-------------|
| **Torrin** | Knowledge base, data layer, evaluation | Neo4j, hybrid search, skill CRUD, eval harness |
| **Griffin** | Agent orchestration, learning logic | Search/create/update routing, Gemini clients, prompts |
| **Josh** | Infrastructure, MCP hosting | FastMCP server, Render deployment, ADK agent |

Pre-written Architecture Decision Records and interface specs enabled fully parallel development from minute one.

## Challenges we ran into

**Lucene query parsing** — Customer utterances contain `!`, `'`, parentheses, and other characters that are special in Lucene's query syntax. Neo4j's fulltext search would crash on raw customer text. We had to add Lucene escaping to sanitize queries before they hit the fulltext index.

**Gemini rate limiting** — At scale, Gemini returns 503 "model overloaded" errors that would silently skip conversations in the eval. We added retry with exponential backoff (2/4/8/16s) that catches transient errors without masking real failures.

**Hybrid search scoring** — Our initial implementation weighted vector scores at 0.7 even when keyword search returned zero results, effectively capping similarity at 70% for valid queries. The fix: base the weighting on whether keyword results *exist*, not on whether query text was provided.

**Shared database isolation** — Three developers running eval against the same Neo4j Aura instance. Cleanup that deletes "all eval skills" would nuke a teammate's data. We solved this with owner-prefixed eval tags and `STARTS WITH` scoping in Cypher cleanup queries.

## Accomplishments we're proud of

- **Measurable improvement** — The evaluation harness proves the learning loop works with real data, not toy examples.
- **Immediate searchability** — No reindexing pipeline. A skill created at 2:00:01 PM is searchable at 2:00:02 PM.
- **43 passing tests** — Unit tests for scoring logic, integration tests against live Neo4j, model validation, resolution heuristics.
- **Clean parallel development** — Three developers, six hours, zero merge conflicts that required manual resolution. Frozen specs + clear ownership.

## What we learned

- **MCP is a powerful abstraction.** By exposing skills as MCP tools rather than a custom API, any agent framework can plug in — Claude, Google ADK, custom bots. The protocol handles the plumbing.
- **Flash-as-judge beats threshold tuning.** Having an LLM make semantic routing decisions ("does this skill match this query?") is more robust than picking a similarity score cutoff, which varies by domain.
- **Evaluation design matters more than model choice.** We spent more time designing *what to measure* (resolution quality, not just latency) than tuning prompts. That investment made the demo story compelling.

## What's next

- **Confidence feedback loop** — User ratings flow back to adjust skill confidence scores, promoting proven playbooks and deprecating stale ones.
- **Skill relationship graph** — "Before using skill X, complete skill Y" — leveraging Neo4j's graph capabilities for prerequisite chains.
- **Multi-agent consensus** — Multiple agents vote on skill quality before it graduates from draft to production.
- **Enterprise deployment** — The MCP protocol means any support platform (Intercom, Zendesk, Salesforce) can connect their existing agent to our skills server and start learning immediately.

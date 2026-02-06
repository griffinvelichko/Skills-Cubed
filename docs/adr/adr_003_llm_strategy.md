# ADR 003: LLM Strategy — Gemini Flash + Pro Split

**Status**: Accepted (updated 2026-02-05)
**Date**: 2026-02-05
**Context**: Hackathon architecture decision, updated after research sprint

## Decision

Use a two-tier LLM strategy:
- **Gemini Flash**: LLM-as-judge for skill matching, playbook execution support, sentiment analysis
- **Gemini Pro**: Skill extraction from conversations, skill refinement/update

## Why Two Tiers

| Task | Model | Why |
|------|-------|-----|
| **Skill matching (judge)** | Flash | Speed. Reads query + candidates, returns one match or "none". ~200ms. Runs on every query. |
| **Sentiment analysis** | Flash | Speed + cost. Simple classification task. |
| **Skill extraction** | Pro | Quality. Extracting a structured `.md` playbook (Do/Check/Say steps) from a messy conversation requires reasoning. |
| **Skill refinement** | Pro | Quality. Merging agent deviations back into an existing playbook requires careful reasoning. |

The learning effect means Pro is called less over time: as the skill library grows, more queries are answered by Flash (judge finds a playbook) instead of Pro (reasons from scratch). This is the cost curve the benchmark shows.

## Flash as Judge

The key architectural decision: Flash decides whether any retrieved playbook matches the customer's query. This replaces threshold-based scoring (arbitrary cutoffs on retrieval scores). Flash makes a semantic judgment — it understands that "I can't log in" matches a password reset playbook but not a password change policy playbook, even if cosine similarity scores them similarly.

The judge prompt returns `{"skill_id": "..."}` or `{"skill_id": "none"}`. Binary. One playbook or nothing.

## Three Prompt Templates

| Prompt | Model | Location | Purpose |
|--------|-------|----------|---------|
| Judge | Flash | `src/orchestration/query_router.py` | "Does any playbook solve this customer's problem?" |
| Extraction | Pro | `src/llm/prompts.py` | "Extract a `.md` playbook from this conversation transcript" |
| Refinement | Pro | `src/llm/prompts.py` | "Merge these agent deviations into this existing playbook" |

## Why Gemini (Not OpenAI, Anthropic, etc.)

- **Hackathon sponsor**: Google DeepMind is co-hosting. Gemini API access is provided.
- **Flash is genuinely fast**: Sub-200ms for judge calls. Good for demo responsiveness.
- **Unified API**: Same SDK for both tiers. One client, two model strings.

## Implementation

Griffin owns `src/llm/`. Single client module, two model configs:

```python
FLASH_MODEL = "gemini-2.0-flash"
PRO_MODEL = "gemini-2.0-pro"

async def call_flash(prompt: str, **kwargs) -> str:
    """Fast, cheap. Use for judge, sentiment, formatting."""
    ...

async def call_pro(prompt: str, **kwargs) -> str:
    """Capable. Use for skill extraction and refinement."""
    ...
```

## Prompt Management

- Prompts live alongside the code that uses them (not in a separate prompts directory)
- Keep prompts as simple as possible — no few-shot examples unless accuracy requires it
- Structured output via Gemini's JSON mode where possible

## Fallback

If Gemini API has issues during the hackathon:
- Flash tasks → try Pro (slower but works)
- Pro tasks → no fallback. Flag and debug.
- If both are down → the hackathon is effectively paused. Escalate to mentors.

## Consequences

- Griffin builds the LLM client module (`src/llm/`) with two entry points (flash/pro)
- Griffin's orchestration layer (`src/orchestration/`) uses Flash for judge calls and Pro for extraction/refinement
- Josh's server calls Griffin's orchestration layer via tool handlers
- Torrin's evaluation harness (`src/eval/`) tracks which model handled each query to show the cost curve
- Embedding generation (for Neo4j vector search) uses a separate Gemini embedding model. Griffin's LLM/orchestration layer computes embeddings for both write-time (skill creation) and query-time (search). The DB layer never imports LLM code — it only accepts pre-computed vectors.

# Bootstrap Prompt: Torrin Phase 2 — Eval Harness & Integration

You are a Claude Code instance working for **Torrin** on the Skills-Cubed project. You are starting a **clean-slate session** — you have no memory of previous work. This document is your complete context.

Read it fully before doing anything. Understand the "why" behind every decision before touching any code. The previous instance spent significant effort getting contracts right — undoing that work is the single worst thing you can do.

---

## Who You Are

**Torrin** — Knowledge base & data layer owner. You own Neo4j, schema, hybrid search, skill CRUD, indexing, and evaluation. You lead the evaluation effort: designing and running tests that prove the agent improves over time. You coordinate end-to-end testing once all pieces land.

You are one of three developers:
- **Griffin** — Orchestration & learning logic. Owns the Flash judge, embedding computation, skill extraction (Gemini Pro), create/update pipelines.
- **Josh** — Infrastructure & MCP hosting. Owns server startup, endpoints, auth, deployment.

Each person runs their own Claude Code instance. The shared contract is the spec. Code aligns to spec. Do not deviate.

---

## What's Already Done (Phase 1, merged via PR #2)

### Contract Freeze — LOCKED, DO NOT CHANGE

These decisions are final. They were made to resolve 6 spec/code conflicts and align all three workstreams. Changing them will break Griffin and Josh's code.

| Decision | Current State | Why |
|----------|--------------|-----|
| Field is `resolution_md`, never `resolution` | All models, DB, specs aligned | Field contains Markdown playbooks — name says so |
| `SkillMatch.confidence`, not `score` | `src/server/models.py:13` | Represents historical success rate, not search relevance |
| `SearchResponse.skill: SkillMatch \| None` | `src/server/models.py:19` | Flash judge picks ONE playbook or nothing |
| `SearchRequest` has `query: str` only | `src/server/models.py:7` | `top_k`/`min_score` are internal pipeline config |
| `NEO4J_USERNAME` preferred (accepts `NEO4J_USER` fallback) | `src/db/connection.py:14` | Matches Aura's generated `.env`; fallback prevents teammate breakage |
| Eval metrics: `skill_found`, `judge_hit_rate`, `pro_fallback_rate` | `src/eval/metrics.py` | Matches judge-based search (skill \| None), not score-based |
| DB layer never computes embeddings | `src/db/queries.py` | Orchestration layer (Griffin) owns embedding computation |

### DB Query Layer — PROVEN, 25 TESTS PASS

All 5 functions in `src/db/queries.py` are implemented and tested against real Neo4j Aura:

```python
async def get_skill(skill_id: str) -> Skill | None
async def create_skill(skill: Skill) -> Skill
async def check_duplicate(embedding: list[float], threshold: float = 0.95) -> Skill | None
async def update_skill(skill_id: str, updates: SkillUpdate) -> Skill  # raises ValueError if not found
async def hybrid_search(query_embedding, query_text, top_k=5, min_score=0.0) -> list[dict]
    # Returns [{"skill": Skill, "score": float}]
```

**`_merge_scores()`** is extracted as a pure function for testable scoring logic. 17 unit tests cover all edge cases. **Do not inline it back into `hybrid_search`.**

**Critical scoring detail**: Weighting (0.7 vec + 0.3 kw vs vector-only) is based on whether `kw_records` is non-empty, NOT on whether `query_text` was non-empty. This prevents a 0.7 cap on vector scores when fulltext returns zero rows for a valid query. Two regression tests in `TestKeywordEmptyFallback` guard this. Do not change the weighting logic without understanding this.

### Startup Hook — EXPORTED, NOT YET WIRED

`src/db/__init__.py` exports `ensure_indexes()`. Josh must call `await ensure_indexes()` in server startup before serving traffic. **This has not been wired yet** — it's Josh's responsibility. If you discover Josh hasn't done it yet when testing end-to-end, remind him.

### Test Infrastructure

- `tests/test_db/test_score_merge.py` — 17 unit tests, no Neo4j needed, always run
- `tests/test_db/test_queries.py` — 8 integration tests, skip without creds, pass against Aura
- `tests/test_db/test_connection.py` — 3 connection tests (1 has pre-existing SSL teardown race)
- **Venv**: Use `venv/bin/python3` and `venv/bin/pytest` — system Python lacks neo4j
- **Neo4j creds**: In `.env` (gitignored). Env vars: `NEO4J_URI`, `NEO4J_USERNAME` (or `NEO4J_USER` fallback), `NEO4J_PASSWORD`
- To run integration tests: `set -a && source .env && set +a && venv/bin/pytest tests/test_db/test_queries.py -v`

---

## What's NOT Done (Your Phase 2 Work)

### Priority 1: Evaluation Harness (`src/eval/harness.py`)

**Why this matters**: The demo tells a story: "the system learns and gets better." Without metrics proving this, we have anecdotes, not evidence. The harness is how we generate the improvement curve that makes the demo compelling.

**Current state**: `EvaluationHarness` exists with `run_baseline()` and `run_learning()` stubs raising `NotImplementedError`.

**What it needs to do**:
1. `run_baseline()` — Process dev split conversations (1,004) with no skills in the DB. Every query goes to Gemini Pro. Record `ConversationMetrics` for each.
2. `run_learning()` — Process train conversations (8,034) sequentially. After each successful resolution → Create Skill. After each search hit → Update Skill. Checkpoint every 100 conversations.
3. Both phases record: `skill_found`, `used_pro_fallback`, `resolved`, `model_used`, `resolution_time_ms`.

**Dependencies**: This needs Griffin's orchestration layer (embedding computation, Flash judge, Pro extraction) to exist. If it doesn't exist yet, **stub the Griffin interface and move on** — define what you need from Griffin as function signatures, implement the harness against those stubs, and tell Griffin what to fill in.

**Ground truth**: `data/abcd/data/kb.json` maps subflows to expected action sequences. Resolution = action sequence match. See `docs/specs/evaluation_strategy.md` for the full heuristic.

**Output**: JSON file with per-conversation metrics, checkpoints, and final aggregates. `MetricsTracker.export_json()` already works.

### Priority 2: End-to-End Smoke Test

**Why**: Before demo day, we need to prove the full 3-beat flow works:
1. Search with no skills → skill=None → Pro fallback
2. Create skill from successful resolution → skill in DB
3. Search again → skill found → Flash serves it

This requires all three workstreams integrated. Coordinate with Griffin (orchestration) and Josh (server).

**Approach**: Write a script (e.g., `scripts/smoke_test.py`) that:
- Calls `ensure_indexes()`
- Creates a skill via `create_skill()` (with a synthetic embedding)
- Searches for it via `hybrid_search()` (with a similar embedding)
- Verifies the created skill is returned
- Cleans up

This can run without Griffin/Josh's code — it tests the DB layer in isolation first. Once their pieces land, extend it to test the full MCP pipeline.

### Priority 3: Support Griffin & Josh Integration

When teammates merge their work, things will break. Field name mismatches, import errors, missing function calls. Be ready to:
- Verify their code uses `resolution_md` (not `resolution`)
- Verify their code uses `confidence` (not `score`) on SkillMatch
- Verify Josh calls `await ensure_indexes()` at startup
- Verify Griffin passes pre-computed embeddings to DB functions (DB never computes embeddings)
- Run the full test suite and fix what breaks

---

## Guiding Principles

These are not suggestions. They are the standards that kept Phase 1 clean.

**1. Simplicity over cleverness.** The `_merge_scores` function is 55 lines of straightforward Python. No abstraction layers, no strategy patterns, no configurable weight parameters. Three similar if-statements are better than a premature abstraction. Write code a tired developer can read at 2 AM.

**2. Test the thing that matters.** We have 17 unit tests for scoring math because scoring math has subtle edge cases. We have 0 tests for `to_neo4j_props()` because it's `return self.model_dump()`. Don't write tests for glue code. Don't skip tests for logic.

**3. Spec is canonical.** When code disagrees with spec, code is wrong. When you're unsure about a decision, read `docs/specs/mcp_tools_spec.md`. When you need to make a new decision, update the spec first, then write the code.

**4. Let errors surface.** `create_skill` uses `result.single()` (strict). `update_skill` raises `ValueError` on not-found. Don't wrap everything in try/except. Catch specific exceptions at boundaries (API endpoints, DB calls). A silent failure during the demo is worse than a loud crash during development.

**5. Don't block on teammates.** If Griffin's orchestration layer doesn't exist yet, stub the interface. Define what you need (function signatures, input/output types), build against the stubs, and tell Griffin what to fill in. Phase 1 worked because we didn't wait — we built the DB layer with stubs for the server that didn't exist yet.

**6. Prove it works.** Every claim needs evidence. "The DB layer works" is backed by 25 passing tests. "The system improves" needs to be backed by the harness output showing an improvement curve. Unproven claims don't go in the demo.

---

## Key Files Reference

| File | Owner | Status | What |
|------|-------|--------|------|
| `src/db/queries.py` | Torrin | **Done** | 5 query functions + `_merge_scores` |
| `src/db/connection.py` | Torrin | **Done** | Driver, indexes, migrations |
| `src/db/__init__.py` | Torrin | **Done** | `ensure_indexes()` export |
| `src/skills/models.py` | Torrin | **Done** | `Skill`, `SkillUpdate` Pydantic models |
| `src/eval/metrics.py` | Torrin | **Done** | `ConversationMetrics`, `AggregateMetrics`, `MetricsTracker` |
| `src/eval/harness.py` | Torrin | **Stub** | `EvaluationHarness` — YOUR MAIN DELIVERABLE |
| `src/server/models.py` | Josh | **Done** | Request/Response Pydantic models |
| `src/server/` | Josh | **Stub** | No app.py yet — Josh builds this |
| `src/orchestration/` | Griffin | **Stub** | Decision layer, judge, tool routing |
| `src/llm/` | Griffin | **Stub** | Gemini Flash/Pro clients |
| `src/analysis/` | Griffin | **Stub** | Sentiment analysis, pattern extraction |
| `tests/test_db/test_score_merge.py` | Torrin | **Done** | 17 unit tests |
| `tests/test_db/test_queries.py` | Torrin | **Done** | 8 integration tests |
| `docs/specs/mcp_tools_spec.md` | All | **Frozen** | Tool contracts — DO NOT CHANGE |
| `docs/specs/evaluation_strategy.md` | Torrin | **Updated** | Judge-era metrics |

---

## First Steps When You Start

1. `git pull origin main` — Get the merged PR #2.
2. Read `CLAUDE.md` — Project overview, conventions, what not to do.
3. Read `docs/specs/evaluation_strategy.md` — Your harness design target.
4. Read `src/eval/harness.py` and `src/eval/metrics.py` — Understand the stub and the metrics contract.
5. Check what Griffin and Josh have merged since PR #2 — their code may be ready to integrate with.
6. Plan the harness implementation. Think about what you need from Griffin's orchestration layer. If it doesn't exist, define the interface and stub it.
7. Run `venv/bin/pytest tests/ -v` to verify the baseline is green.

---

## Explicit Do-Not-Change List

These are things the previous instance got right. Changing them causes contract drift:

- `_merge_scores` weighting logic (kw_records presence, not query_text presence)
- `Skill.resolution_md` field name
- `SkillMatch.confidence` field name
- `SearchResponse.skill: SkillMatch | None` shape
- `SearchRequest` having only `query: str`
- `hybrid_search` signature (accepts pre-computed embeddings, never computes them)
- `ConversationMetrics` field names (`skill_found`, `used_pro_fallback`)
- `AggregateMetrics` field names (`judge_hit_rate`, `pro_fallback_rate`)
- `ensure_indexes()` as the public startup hook

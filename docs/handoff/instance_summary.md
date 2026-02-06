# Instance Summary: Torrin Phase 1 — DB Query Layer

**Instance**: Claude Opus 4.6, Torrin's workstream
**Date**: 2026-02-06
**Branch**: `torrin/db-query-layer` (PR #2, pending merge to main)
**Duration**: Single session, ~30 agentic turns
**Reviewer**: Codex (3 review cycles, all flags resolved)

---

## What We Started With

The repo had a bootstrap commit (`8e0a614`) containing:
- Pydantic models with field stubs (`src/skills/models.py`, `src/server/models.py`)
- A Neo4j connection helper (`src/db/connection.py`) with `get_driver()`, `health_check()`, `initialize_indexes()`
- Query function stubs in `src/db/queries.py` — all 5 functions raised `NotImplementedError`
- Eval metric dataclasses and a stubbed `EvaluationHarness`
- Spec docs (`docs/specs/mcp_tools_spec.md`, `docs/specs/evaluation_strategy.md`)
- No tests beyond 3 basic connection tests

**The problem**: The bootstrap was written before teammates finalized the specs. Six conflicts existed between what the spec documents said and what the code declared. Griffin and Josh were blocked waiting for a working DB layer.

---

## What We Did and Why

### 1. Contract Freeze (Step 0)

**Why**: Spec drift is poison in a 3-person hackathon. If Torrin's DB layer says `resolution` but Griffin's orchestration says `resolution_md`, integration fails at demo time. We had to pick one source of truth and align everything to it before writing any logic.

**Decision**: Spec is canonical. Code aligns to spec. Every conflict was resolved spec-ward:

| Conflict | Resolution | Reasoning |
|----------|-----------|-----------|
| `resolution` vs `resolution_md` | Renamed to `resolution_md` everywhere | Spec is explicit — the field contains Markdown playbooks, the name should say so |
| `SkillMatch.score` vs `confidence` | Renamed to `confidence` | The field represents historical success rate, not search relevance score. Score is an internal concept in hybrid_search |
| `SearchResponse.matches: list` vs `skill: SkillMatch \| None` | Single match | The Flash judge picks ONE playbook or nothing. A ranked list implies the caller (external agent) should choose — that's wrong, the judge chooses |
| `SearchRequest.top_k, min_score` | Removed from public API | These are internal pipeline config. The calling agent just says "here's a query" — it doesn't know or care about retrieval parameters |
| Fulltext index on `n.resolution` | Changed to `n.resolution_md` | Follows from the field rename. Added DROP/CREATE migration because `IF NOT EXISTS` won't update an existing index |
| `NEO4J_USER` vs `NEO4J_USERNAME` | Changed to `NEO4J_USERNAME` | Matches what Neo4j Aura actually puts in the `.env` file it generates |

**Files changed**: `src/skills/models.py`, `src/server/models.py`, `src/db/connection.py`, `tests/test_db/test_connection.py`

**Migration added**: `initialize_indexes()` now includes a one-time data migration that copies `resolution` → `resolution_md` on any legacy nodes that have the old field name, then removes the old field. This prevents `Skill.from_neo4j_node()` from crashing on stale data.

### 2. Query Layer Implementation (Step 2)

**Why**: This is the critical path. Griffin's orchestration layer calls these functions. Josh's server endpoints call these functions. Neither can build their pieces until these work.

Five functions implemented in `src/db/queries.py`:

**`get_skill(skill_id) → Skill | None`** (lines 8-18)
- Simple MATCH query. Uses `result.single(strict=False)` because not-found is a valid outcome (returns None), not an error.
- Why `strict=False`: The neo4j driver's `single()` raises by default when there are zero results. We want None.

**`create_skill(skill) → Skill`** (lines 21-29)
- Uses `skill.to_neo4j_props()` to flatten the Pydantic model to a dict.
- Uses `result.single()` (strict) because CREATE should always return a result — if it doesn't, something is seriously wrong and we want the error.
- Returns the Skill reconstructed from DB response, not the input, because the DB round-trip proves the data persisted correctly.

**`check_duplicate(embedding, threshold) → Skill | None`** (lines 32-49)
- Vector index query for top-1 nearest neighbor.
- Returns the existing Skill only if similarity > threshold (default 0.95).
- Called by Griffin's create pipeline before writing a new skill — prevents near-duplicate playbooks.

**`update_skill(skill_id, updates) → Skill`** (lines 52-74)
- Builds a changes dict from non-None fields in `SkillUpdate.model_dump()`.
- Single MATCH + SET query that also increments `version` and sets `updated_at`.
- Raises `ValueError` if MATCH finds nothing — the caller should have verified the skill exists first, so a missing skill here is a bug.
- Validates embedding dimension before the DB write if `updates.embedding` is provided — a bad vector would persist and break Skill reconstruction on subsequent reads.

**`hybrid_search(query_embedding, query_text, top_k, min_score) → list[dict]`** (lines 77-121)
- Two-phase: vector index query, then fulltext query (skipped if query_text is empty/whitespace).
- Over-fetches by 2x (`fetch_count = top_k * 2`) to catch skills that rank differently across the two sub-queries.
- Delegates all scoring math to `_merge_scores()`.

**`_merge_scores()` — extracted pure function** (lines 124-178)
- **Why extracted**: The scoring logic has subtle edge cases (BM25 normalization when all scores are equal, clamping, empty-result fallback). These need deterministic unit tests. Testing them through `hybrid_search` requires a live Neo4j connection. Extracting to a pure function lets us test 17 edge cases with zero infrastructure.
- **Weighting**: 0.7 * vector + 0.3 * keyword when keyword results exist. Vector-only when no keyword results.
- **BM25 normalization**: Min-max within the result set. When all scores are identical (range=0), all normalize to 1.0.
- **Critical design choice**: Weighting decision is based on `bool(kw_scores)` (whether keyword results actually exist), NOT on whether `query_text` was non-empty. See "Bugs Found" below.

### 3. Startup Hook (ensure_indexes)

**Why**: `hybrid_search` and `check_duplicate` call Neo4j index procedures. On a fresh Aura DB, those indexes don't exist. Without an init call, the very first search at demo time would crash.

**What we did**: Added `ensure_indexes()` to `src/db/__init__.py` as the public entry point. Josh imports it and calls `await ensure_indexes()` in his server startup before accepting MCP traffic.

**Why not call it automatically**: We don't own the server module. Josh controls the startup sequence. The DB package exports the function; Josh calls it when he's ready.

### 4. Eval Metrics Alignment

**Why**: The eval spec had been updated to describe judge-based search (skill | None), but the code still had score-based fields (`search_hit`, `search_score`, `search_hit_rate`, `avg_search_score`). If Griffin builds the harness against these old fields, the eval results will measure the wrong thing.

**What we changed**:
- `ConversationMetrics`: `search_hit` → `skill_found`, `search_score` → `used_pro_fallback`
- `AggregateMetrics`: `search_hit_rate` → `judge_hit_rate`, `avg_search_score` → `pro_fallback_rate`
- `MetricsTracker.aggregate()`: Updated to compute the new fields
- `evaluation_strategy.md`: Updated metric names and Phase 3 recording list

---

## Bugs Found and Fixed

### Scoring Weighting Bug (critical)

**The bug**: `has_keyword` was derived from `query_text and query_text.strip()` — i.e., "did the caller provide a keyword query?" This was passed to `_merge_scores` and used to decide weighting. If `has_keyword=True`, all scores got 0.7 * vec + 0.3 * kw.

**The problem**: When `query_text` is "password reset" but fulltext returns zero rows (possible — the fulltext index might not have relevant content yet), `kw_records` is empty. Every vector-only skill gets `0.7 * vec + 0.3 * 0.0 = 0.7 * vec`. A skill with vector score 0.85 becomes 0.595. With `min_score=0.6`, it gets **wrongly filtered out**. The first demo query on a fresh database would fail.

**The fix**: `_merge_scores` no longer takes a `has_keyword` parameter. It computes `has_keyword_results = bool(kw_scores)` internally — the weighting decision is based on whether keyword results actually exist, not whether a keyword query was attempted.

**Test coverage**: `TestKeywordEmptyFallback` class with 2 regression tests that would fail under the old logic.

### Event Loop Stale Driver (test infrastructure)

**The bug**: A `session`-scoped async fixture created a Neo4j driver on one event loop. Individual tests (function-scoped) got different event loops. The global `_driver` singleton was attached to the dead first loop.

**The fix**: `_reset_driver` autouse fixture sets `connection._driver = None` before each test, plus cleans up stale test data on first run. Each test gets a fresh driver bound to its own event loop.

### Stale Test Data in Aura

**The bug**: Previous test runs left Skill nodes in the DB. `check_duplicate` and `hybrid_search` found those stale nodes instead of the freshly-created test skill.

**The fix**: The `_reset_driver` fixture deletes all nodes with `title STARTS WITH 'Test: '` on first run.

---

## What's Proven (tested against real Aura)

| Component | Status | Evidence |
|-----------|--------|----------|
| `get_skill` | **Proven** | `test_create_and_get`, `test_get_skill_not_found` pass |
| `create_skill` | **Proven** | `test_create_and_get` pass — node verified in DB |
| `update_skill` | **Proven** | `test_update_skill` — version increments, fields update |
| `check_duplicate` | **Proven** | `test_check_duplicate` — finds same embedding, rejects different |
| `hybrid_search` | **Proven** | `test_hybrid_search`, `test_hybrid_search_vector_only`, `test_hybrid_search_min_score_filter` |
| `_merge_scores` | **Proven** | 17 deterministic unit tests covering all edge cases |
| `initialize_indexes` | **Proven** | Runs in test fixture, indexes exist in Aura |
| Contract freeze | **Proven** | All imports resolve, models validate, tests pass. No active schema field named `resolution`; only legacy migration cleanup references it (`connection.py:77`) |

## What's Unproven (no test coverage yet)

| Component | Status | Risk | Owner |
|-----------|--------|------|-------|
| Server startup calling `ensure_indexes()` | **Not wired** | First boot on fresh DB crashes | Josh |
| Flash judge selecting from hybrid_search candidates | **Not built** | Core search UX doesn't work | Griffin |
| Orchestration embedding computation | **Not built** | No queries can run without embeddings | Griffin |
| `EvaluationHarness.run_baseline()` / `run_learning()` | **Stubbed** | Can't measure improvement | Torrin |
| End-to-end 3-beat demo flow | **Not tested** | Demo fails | All |

---

## Files Changed (complete list)

| File | Change Type | Lines | What |
|------|-------------|-------|------|
| `src/skills/models.py` | Modified | 93 | `resolution` → `resolution_md` (field, create_new param, kwarg) |
| `src/server/models.py` | Modified | 59 | `score` → `confidence`, `resolution` → `resolution_md`, single match, query-only request |
| `src/db/connection.py` | Modified | 83 | `NEO4J_USERNAME`, fulltext index migration, data migration |
| `src/db/__init__.py` | Modified | 11 | `ensure_indexes()` export for server startup |
| `src/db/queries.py` | Modified | 178 | All 5 query functions + `_merge_scores` |
| `src/eval/metrics.py` | Modified | 71 | Judge-based metric fields |
| `tests/test_db/test_connection.py` | Modified | 39 | `NEO4J_USERNAME` in skip check |
| `tests/test_db/test_queries.py` | **New** | 157 | 8 integration tests |
| `tests/test_db/test_score_merge.py` | **New** | 183 | 17 unit tests |
| `docs/specs/mcp_tools_spec.md` | Modified | 186 | `min_score` in hybrid_search contract |
| `docs/specs/evaluation_strategy.md` | Modified | 99 | Judge hit rate, pro fallback rate |

---

## Architectural Decisions and Reasoning

1. **Spec is canonical, code aligns to spec**: In a 3-person team with each person running their own Claude instance, the spec is the shared contract. If code drifts from spec, each instance makes different assumptions and integration fails. We froze the contract first, before writing any logic.

2. **DB layer never computes embeddings**: This is a boundary decision documented in the spec. The orchestration layer (Griffin) owns embedding computation. The DB layer only accepts pre-computed vectors. This keeps the DB layer stateless and testable — no Gemini API dependency in the data path.

3. **_merge_scores as a pure function**: The alternative was testing scoring logic through `hybrid_search` (requires live Neo4j). Extracting it costs one function boundary but gains 17 deterministic tests that run in 3 seconds with zero infrastructure. The scoring bug we caught would have been nearly impossible to debug through integration tests alone.

4. **Single-match search response**: The spec says the Flash judge picks one playbook or nothing. A list response implies the caller should choose. In a continual-learning MCP server, the whole point is that the system learns what works — the system makes the decision, not the calling agent.

5. **min_score stays internal**: The calling agent says "search for X". How the pipeline scores and filters is an implementation detail. Exposing it creates a coupling that would break if we change scoring weights or add new signals.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|-----------|-------|
| Query functions work correctly | **High** | 8 integration tests pass against real Aura |
| Scoring math is correct | **High** | 17 edge case unit tests, keyword-empty bug explicitly covered |
| Contract freeze is complete | **High** | No remaining `resolution` or `search_hit` references in src/ |
| Eval harness will work when wired | **Medium** | Metrics are aligned but harness is still stubbed |
| Demo will work end-to-end | **Low** | Server startup, orchestration, and judge are all unbuilt |
| Test infrastructure is robust | **Medium** | Event loop fix works but relies on global driver reset — fragile |

---

## What the Next Instance Needs to Know

1. **Do not re-open the contract freeze**. The field names, response shapes, and API boundaries are decided. Changing them breaks Griffin and Josh's work.

2. **The scoring bug fix is subtle**. If anyone touches `_merge_scores`, they must understand that weighting is based on `kw_records` presence, not `query_text` presence. The `TestKeywordEmptyFallback` tests exist specifically to catch regressions.

3. **`ensure_indexes()` must be called before first query**. This is the #1 integration risk. Josh needs to wire it into server startup.

4. **The eval harness is the next Torrin deliverable**. The metrics are aligned, the DB layer works, but `run_baseline()` and `run_learning()` are still stubs. This is the highest-leverage work for proving the demo story.

5. **Neo4j creds are in `.env`** (gitignored). The canonical env var is `NEO4J_USERNAME`; `connection.py` also accepts `NEO4J_USER` as fallback for teammates who haven't updated their `.env`.

# Instance Summary: Pre-Hackathon Bootstrap Session

**Instance**: Claude Opus 4.6, working as Torrin (KB & data layer owner)
**Repo at session start**: `griffinvelichko/Skills-Squared` — zero code, docs only
**Repo at session end**: `griffinvelichko/Skills-Cubed` — full bootstrap, Codex-verified, ready for Block 1
**Date**: 2026-02-05 (night before hackathon)

---

## What This Session Accomplished

Took the project from architectural documents to a working, Codex-verified codebase foundation. Built the integration contracts that three developers will code against in parallel during the hackathon.

### The 8 original commits (Skills-Squared)

```
011216f [docs] add hackathon bootstrap docs, CLAUDE.md, specs, and ADRs
8d5aa26 [bootstrap] add project scaffolding and directory structure
6f1d056 [models] add Pydantic models for skills and MCP tools
57fc153 [db] add Neo4j connection skeleton and health check
66f603d [eval] add evaluation strategy, metrics tracking, and ABCD exploration
e5a0d0c [docs] fix spec contract conflicts and update for ABCD pivot
d4d104e [fix] address Codex review findings — validation, stubs, data bootstrap
2677c38 [fix] align spec flow diagrams with code signatures
```

### The 3 migration commits (Skills-Cubed)

```
f1813c5 [docs] — all 17 doc files
8e0a614 [bootstrap] — all 26 code/config/test files
4c36abe [sync] — teammate additions from Skills-Squared main (Josh's hosting, doc edits)
```

---

## The Reasoning Behind Every Decision

### Why this sequence (scaffolding → models → DB → eval → docs)

The sequencing was deliberate. `pyproject.toml` first so teammates can `pip install` immediately. Models second because they're the **integration boundary** — Griffin's orchestration imports `Skill`, Josh's server imports `SearchRequest`. If models are wrong, everything downstream breaks. DB skeleton third because it's the foundation I own. Eval fourth because it depends on understanding the dataset. Doc fixes last because they're retroactive corrections.

### Why model_validator on Skill (not just factory validation)

The original design validated embedding dimension only in `create_new()`. Codex correctly identified that `Skill(...)` direct construction — which `from_neo4j_node()` uses internally — could bypass validation entirely. A bad embedding could enter the system from stored Neo4j data and never be caught.

The `model_validator(mode="after")` fires on **every construction path**: `create_new()`, `from_neo4j_node()`, direct `Skill(...)`. It enforces: embedding non-empty, embedding dimension == `EMBEDDING_DIM`, timestamps non-empty. This was the single most important code quality fix in the session.

### Why typed stubs with NotImplementedError (not empty __init__.py)

Three developers coding in parallel against the same interfaces. If Griffin writes `from src.db.queries import hybrid_search` and the function doesn't exist, he'll invent his own signature. When Torrin implements the real version, the signatures won't match. Integration breaks.

The typed stubs are a **contract**: they say "this is exactly the function signature, return type, and parameter names you'll get." Griffin and Josh can import, type-check, and write tests against them today. The `NotImplementedError` makes it obvious when you hit unimplemented code vs a real bug.

### Why validate_embedding fires before NotImplementedError in stubs

Even unimplemented, the boundary validation catches wrong-dimension embeddings immediately. If Griffin accidentally passes a 512-dim vector, he gets `ValueError: Expected embedding dim 768, got 512 (hybrid_search)` — not a mysterious failure later when the real implementation lands.

### Why the DB layer never imports LLM code

ADR 003 originally said embedding generation was "a DB-layer concern." This was wrong and created an ownership conflict. We fixed it: the orchestration/LLM layer computes ALL embeddings. The DB layer only accepts pre-computed vectors.

**Why this matters**: If `src/db/` imports the Gemini client, you can't run DB tests without a Gemini API key. You can't test queries without LLM infrastructure. Clean separation means each layer is independently testable.

### Why hybrid score normalization was spec'd with edge cases

BM25 (keyword) scores are unbounded. Vector (cosine) scores are [0,1]. If you combine them naively, keyword matches dominate and results are nonsensical. The normalization spec prevents this:
1. Vector: raw (already [0,1])
2. Keyword: min-max within result set
3. Combined: 0.7 * vector + 0.3 * keyword
4. Clamp to [0,1]
5. Apply min_score filter AFTER combining

The edge cases (`max == min` → all scores = 1.0, single result → score = 1.0) prevent division-by-zero in production. These are easy to miss and hard to debug.

### Why ABCD over Syncora

Syncora was synthetic. ABCD has real human conversations AND `kb.json` — a mapping from 55 subflows to their required action sequences. This is ground truth we can evaluate against objectively. We don't have to guess whether the system "learned correctly" — we can compare its output to the expected action sequence.

---

## What I'm Confident In

1. **Models are internally correct and safe.** Two Codex review rounds. Validation catches empty embeddings, wrong dimensions, missing timestamps on all construction paths. Round-trip serialization (Skill → Neo4j props → Skill) works. **However**, model field names may no longer match the specs after teammate edits — see "What I'm NOT Confident In" below.

2. **Spec/code alignment WAS exact at time of bootstrap, but has since drifted.** Teammates modified `mcp_tools_spec.md` and `skill_schema_spec.md` after our bootstrap. The "DB Layer Contracts" section still reflects our original signatures, but other parts of the same spec now contradict them. **A contract freeze is needed before implementation.** See drift inventory below.

3. **ABCD dataset understanding is thorough.** 10,042 conversations, 10 flows, 96 subflows, 46 overlap with kb.json ground truth. The `scripts/explore_abcd.py` output is verified.

4. **Architecture is clean.** No circular dependencies. Each module imports only what it needs. DB layer depends on models + config only. Server models are standalone.

---

## What I'm NOT Confident In — CRITICAL FOR NEXT INSTANCE

### 1. Spec drift from teammate changes (HIGH PRIORITY — CONTRACT FREEZE NEEDED)

When we synced Skills-Squared main → Skills-Cubed, we brought in teammate modifications to several spec files. I did NOT deeply reconcile these with our code models. A subsequent Codex review identified **active drift across multiple files**. The next instance MUST resolve all of these before implementing any DB queries.

#### Full Drift Inventory

| Spec says | Code says | Files in conflict |
|-----------|-----------|-------------------|
| `resolution_md` (field name) | `resolution` (field name) | `mcp_tools_spec.md:35`, `skill_schema_spec.md:96,131` vs `src/skills/models.py:17`, `src/server/models.py:16`, `src/db/connection.py:64` |
| `SearchResponse.skill: SkillMatch \| None` (single match or None) | `SearchResponse.matches: list[SkillMatch]` (list) | `mcp_tools_spec.md:27` vs `src/server/models.py:21` |
| `hybrid_search(..., top_k)` (no min_score) | `hybrid_search(..., top_k, min_score)` (has min_score) | `mcp_tools_spec.md:169` vs `src/db/queries.py:9` |
| Fulltext index on `n.resolution_md` | Fulltext index on `n.resolution` | `skill_schema_spec.md:131` vs `src/db/connection.py:64` |
| `confidence` field in SkillMatch | `score` field in SkillMatch | `mcp_tools_spec.md:34` vs `src/server/models.py:15` |
| Skills are .md playbooks with Do/Check/Say format | `resolution: str` (plain string) | `skill_schema_spec.md:67-86` vs `src/skills/models.py:17` |
| Embedding = problem + conditions + keywords, NOT resolution | No embedding scope defined in model | `skill_schema_spec.md:99` vs `src/skills/models.py:22` |
| Evaluation uses score/min_score semantics for search hit rate | Search spec now describes single match + judge, not score thresholding | `evaluation_strategy.md:11,45` vs `mcp_tools_spec.md:27,52-55` |
| Dataset mapping says `skill.resolution` | Updated schema/spec trend uses `resolution_md` playbook naming | `adr_004_dataset_choice.md:26` vs `skill_schema_spec.md:18` |

#### What this means

These are not cosmetic differences — they will cause runtime failures if left unresolved. The team needs to make a **contract freeze decision** on each conflict before any implementation proceeds:
- Is the field called `resolution` or `resolution_md`?
- Does search return a single match or a list?
- Does `hybrid_search` take `min_score`?
- What does the SkillMatch response look like?

**The next instance's FIRST action must be to read all specs, identify which version is canonical, and update either the specs or the code to match.** Do not implement against ambiguous contracts.

### 2. Venv in Skills-Cubed

The pip install ran from the wrong working directory during migration and may have incomplete dependencies. The next instance should run `venv/bin/pip install -e ".[dev]"` from the Skills-Cubed root and verify all imports before proceeding.

### 3. No real Neo4j testing

All 3 DB tests skip without credentials. The connection skeleton and index creation have never been tested against the actual Aura instance. First thing with real creds: run `venv/bin/pytest tests/test_db/ -v` and fix any issues.

### 4. Josh's hosting additions

`docs/adr/adr_004_hosting_strategy.md` and `docs/specs/hosting_spec.md` describe Render deployment with `USE_MOCK_DB` env var pattern and FastMCP as the server framework. Josh may be using `fastmcp` (not just `fastapi`) — this could affect how the server imports our models. I haven't verified compatibility.

---

## What Was Left Undone

| Item | Why | Priority for next instance |
|------|-----|---------------------------|
| Implement 5 DB query stubs | Main hackathon Block 1 work | **P0 — the whole point** |
| Reconcile spec drift (resolution_md, embedding scope) | Discovered during migration, ran out of context | **P0 — must do before implementing** |
| Create `.env` with real creds | Needs actual Neo4j + Gemini credentials | P1 |
| Fix Skills-Cubed venv | pip ran from wrong CWD | P1 |
| Implement eval harness | Depends on queries working | P2 |
| Add typed return model for hybrid_search | Codex suggestion, returns `list[dict]` currently | P3 |
| Fix pytest-asyncio warning | `asyncio_mode` config not recognized by installed version | P3 |

---

## Key Files Reference

| File | What to know |
|------|-------------|
| `CLAUDE.md` | Single source of truth. Read first, always. |
| `docs/specs/mcp_tools_spec.md:160-184` | DB contracts from the bootstrap baseline. Treat as provisional until contract freeze resolves current drift. |
| `docs/specs/skill_schema_spec.md` | **HAS BEEN MODIFIED BY TEAMMATES.** Read the whole thing fresh. |
| `src/skills/models.py` | Skill model with model_validator. The integration boundary. |
| `src/db/queries.py` | The 5 stubs to implement. |
| `src/db/connection.py` | Async Neo4j driver, index creation. The foundation. |
| `src/eval/metrics.py` | MetricsTracker — complete and working. |
| `data/abcd/data/kb.json` | Ground truth: 55 subflows → action sequences. |
| `scripts/explore_abcd.py` | Dataset explorer. Run it to verify data is present. |

---

## Environment Notes

- **Python**: Must use `python3` (not `python`). Venv at `Skills-Cubed/venv/`.
- **Working directory**: Project root is `Skills-Cubed/`, not a subdirectory.
- **Data**: `data/abcd/` is cloned but untracked. If missing, run `bash scripts/setup_data.sh`.
- **Build backend**: `setuptools.build_meta` (NOT `setuptools.backends._legacy:_Backend` — that doesn't exist and was a bug we fixed early).

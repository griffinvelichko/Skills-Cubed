# Hackathon Day Bootstrap — Torrin's Claude Instance

Copy-paste this as your first message in a fresh Claude Code session inside the `Skills-Cubed` repo.

---

```
You are helping build Skills-Squared (hosted in the Skills-Cubed repo) — a continual-learning MCP server for customer support. An AI agent handles support conversations, and Skills-Squared learns from successful resolutions — extracting reusable "skill" documents that turn expensive LLM reasoning into fast cached lookups.

This is hackathon day. A prior Claude instance completed the full pre-hackathon bootstrap: scaffolding, Pydantic models, DB skeleton, evaluation design, and documentation. That work has been Codex-reviewed twice with all blocking findings resolved. You are continuing from where it left off.

## Your Role

I'm Torrin — I own src/db/, src/skills/, and src/eval/ (knowledge base, data layer, evaluation). My priority is implementing the Neo4j query layer so Griffin (orchestration) and Josh (server) can integrate against it.

## Before Writing Any Code

Read these files in this order. This is not optional — the specs have been modified by teammates since the bootstrap, and there may be drift between docs and code that must be resolved first.

1. `CLAUDE.md` — Single source of truth for the project.
2. `docs/prompts/instance_summary_bootstrap.md` — Comprehensive summary of the prior session: what was built, why, what's confident, what's NOT confident, and what was left undone. **Read the "What I'm NOT Confident In" section carefully — it flags spec drift that needs resolution before you implement.**
3. `docs/specs/skill_schema_spec.md` — The skill schema. **This was modified by teammates.** Compare it against `src/skills/models.py` and flag any field naming or structural mismatches (e.g., `resolution` vs `resolution_md`, embedding content scope).
4. `docs/specs/mcp_tools_spec.md` — MCP tool contracts. **ALSO modified by teammates.** The SearchResponse shape changed (single match vs list), SkillMatch fields changed (confidence vs score, resolution_md vs resolution), and the "DB Layer Contracts" section (line ~160) omits min_score from hybrid_search while the code stub has it. Compare the response models (lines 26-37) against `src/server/models.py` and the DB contracts against `src/db/queries.py`.
5. `src/skills/models.py` — The Skill model. Has a model_validator that enforces embedding dimension and timestamps on all construction paths.
6. `src/db/queries.py` — The 5 typed stubs you need to implement.
7. `src/db/connection.py` — The async Neo4j driver and index creation you'll build on.
8. `docs/specs/evaluation_strategy.md` — How we measure success. Ground truth is kb.json.

## Environment Setup

The venv may have incomplete deps from an interrupted install during migration. Before anything:

1. Verify venv: `venv/bin/pip install -e ".[dev]"` from repo root
2. Verify data: `venv/bin/python3 scripts/explore_abcd.py` (should print dataset stats)
3. Verify models: `venv/bin/python3 -c "from src.skills.models import Skill; print(list(Skill.model_fields.keys()))"`
4. Create `.env` from `.env.example` with real Neo4j + Gemini creds (ask me for these)
5. Run DB tests: `venv/bin/pytest tests/test_db/ -v` (should pass with creds, skip without)

Use `venv/bin/python3` for all commands. `python` does not exist in this environment.

## Step Zero: Contract Freeze (BEFORE ANY IMPLEMENTATION)

Teammates modified the specs after the bootstrap. There is **active drift** between docs and code that will cause runtime failures if not resolved. The instance summary (`docs/prompts/instance_summary_bootstrap.md`) has a full drift inventory table, but the key conflicts are:

- `resolution` vs `resolution_md` (field naming across models, specs, and fulltext index)
- `SearchResponse.matches: list[SkillMatch]` vs `SearchResponse.skill: SkillMatch | None` (search return shape)
- `hybrid_search` signature: code has `min_score`, spec "DB Layer Contracts" section omits it
- SkillMatch: code has `score: float`, spec has `confidence: float`
- Embedding scope: spec says "problem + conditions + keywords, NOT resolution" — not enforced in code
- Evaluation/docs drift: `evaluation_strategy.md` still references score/min_score semantics while current search spec describes judge-picked single match behavior

**Your first action**: Read the full current specs, compare against the code models and stubs, decide which version is canonical for each conflict (discuss with me if unclear), and update either the specs or the code to match. Do NOT implement queries against ambiguous contracts.

## Implementation Priority: src/db/queries.py

After contracts are frozen, implement the five stubs in this order (optimized for fastest cross-team unblock):

1. **`hybrid_search(...)`** — The hot path. Every search query hits this. Griffin and Josh are blocked until it works. Vector query + fulltext query + score normalization (spec details: min-max for keywords, raw for vectors, 0.7/0.3 weighting, clamp, min_score filter after combining). Handle edge cases.

2. **`check_duplicate(embedding, threshold) -> Skill | None`** — Required by the create flow (spec: duplicate check happens before writing). Vector similarity query, return existing skill if score > threshold.

3. **`create_skill(skill: Skill) -> Skill`** — Write a Skill node to Neo4j. Use `skill.to_neo4j_props()` for properties. Straightforward Cypher CREATE.

4. **`get_skill(skill_id: str) -> Skill | None`** — MATCH by skill_id UUID. Use `Skill.from_neo4j_node()` to reconstruct. Needed by update flow.

5. **`update_skill(skill_id: str, updates: SkillUpdate) -> Skill`** — Get existing skill, merge non-None fields from SkillUpdate, increment version, set updated_at.

Each function already has boundary validation (validate_embedding) wired in for hybrid_search and check_duplicate. Keep that — just implement the logic after the validation call.

## Guiding Principles

These are from CLAUDE.md and are non-negotiable:

- **Move fast, ship working code.** No gold-plating. If it works, commit it.
- **No premature abstraction.** Three similar Cypher queries are fine. Don't extract a query builder.
- **Let errors surface.** Don't wrap Neo4j calls in try/except unless it's at the API boundary. Use `raise`, not `return None`, for unexpected states.
- **Validate at boundaries only.** The model_validator handles Skill construction. validate_embedding handles search/duplicate inputs. Don't add validation inside query logic.
- **Type hints on signatures, skip on obvious locals.** Commit messages: `[module] description`.
- **Everything serves the demo.** Baseline RAG (slow, Pro) → first encounter (learns) → after learning (fast, Flash). Every line of code should make this demo work better.

## What NOT to Do

- Don't refactor existing code that works — UNLESS the contract freeze requires it. The models, config, and connection modules may need field renames or signature changes to match the frozen contracts. Make those changes surgically, then move on.
- Don't add features beyond what the stubs define. No caching, no batch operations, no query optimization. Get the 5 functions working.
- Don't create new files unless absolutely necessary. Everything you need is already scaffolded.
- Don't skip reading the instance summary. It flags critical issues that will bite you if ignored.

## After Queries Are Working

Once all 5 stubs are implemented and tested against real Neo4j:

1. Implement `src/eval/harness.py` — `run_baseline()` and `run_learning()` using the query functions and MetricsTracker.
2. Run a small-scale evaluation: 50-100 train conversations through the learning loop, then test against dev split.
3. Coordinate with Griffin on embedding generation (his orchestration layer computes embeddings, your DB layer accepts them).
4. Coordinate with Josh on server wiring (his endpoints call your query functions via Griffin's orchestration).

## Quick Reference

| What | Where |
|------|-------|
| Skill model (15 fields) | `src/skills/models.py` |
| MCP request/response models (8) | `src/server/models.py` |
| DB stubs to implement | `src/db/queries.py` |
| Neo4j driver + indexes | `src/db/connection.py` |
| Embedding dim + validation | `src/utils/config.py` |
| Metrics tracker | `src/eval/metrics.py` |
| Eval harness stub | `src/eval/harness.py` |
| Ground truth skills | `data/abcd/data/kb.json` |
| Dataset explorer | `scripts/explore_abcd.py` |
| Prior session learnings | `docs/prompts/instance_summary_bootstrap.md` |
| Canonical DB contracts | `docs/specs/mcp_tools_spec.md:160-184` |
| Score normalization spec | `docs/specs/skill_schema_spec.md` (search for "Score Normalization") |
```

---

## Usage

1. Open Claude Code in the Skills-Cubed repo root
2. Paste the prompt above as your first message
3. Claude will read all referenced files, identify any spec drift, and begin implementation
4. Have Neo4j credentials ready — Claude will need them for `.env`

# Codex Reviewer Init Prompt

Use this when submitting a checkpoint review to Codex (or any external LLM reviewer). Copy-paste the block below, then attach the relevant files.

---

```
You are reviewing code for Skills-Squared — a continual-learning MCP server being built in a 6-hour hackathon by 3 developers.

Context:
- FastMCP server with 3 tools: search_skills, create_skill, update_skill
- Skills are executable .md playbooks (Do/Check/Say steps), not knowledge articles
- search_skills: Neo4j hybrid search → Flash judge picks ONE playbook or returns nothing
- create_skill: Gemini Pro extracts .md playbook from conversation transcript
- update_skill: Gemini Pro merges agent deviations into existing .md playbook
- Neo4j database with hybrid search (keyword + vector)
- Gemini Flash (judge, sentiment) + Gemini Pro (extraction, refinement)
- Three developers working in parallel on separate modules, merging to main frequently

Your job is to review the attached code for integration risks and blocking issues ONLY.

Review for:
- Interface mismatches between modules (type mismatches, missing fields, wrong return shapes)
- search_skills returning a single SkillMatch or None (not a list) — verify callers handle both
- resolution_md field usage (not resolution) throughout the codebase
- Flash judge prompt returning valid JSON with skill_id or "none"
- Async/sync boundary issues
- Missing error handling at module boundaries (DB calls, LLM calls, tool handlers)
- Obvious bugs that would break the demo flow

Do NOT review for:
- Code style, formatting, or naming conventions
- Documentation completeness
- Test coverage
- Performance optimization
- "Nice to have" improvements

Verdict format:
- **GO**: No blocking issues found. Briefly note anything worth watching.
- **FLAG [issue]**: Specific issue that would break integration or the demo. Describe the problem and suggest a fix.

Be terse. We have 6 hours total. Your review should take 2 minutes to read.
```

---

## What to Attach

**Checkpoint 1** (Hour 2 — Infrastructure):
- CLAUDE.md
- `docs/specs/mcp_tools_spec.md`
- `docs/specs/skill_schema_spec.md`
- All files in `src/server/`, `src/db/`, `src/llm/`
- Question: "Do these module interfaces match the spec contracts?"

**Checkpoint 2** (Hour 3.5 — Core Logic):
- CLAUDE.md
- `src/` directory (all files)
- Question: "Can a query flow through search (Flash judge returns playbook) → agent executes → create (Pro extracts .md) → search again (Flash judge finds it) without breaking?"

**Checkpoint 3** (Hour 5 — Demo Pipeline):
- CLAUDE.md
- `src/` directory + `scripts/demo.py` (or equivalent)
- Question: "Will the 3-beat demo (baseline playbook execution → first encounter with Pro reasoning → after learning with playbook execution) work end-to-end?"

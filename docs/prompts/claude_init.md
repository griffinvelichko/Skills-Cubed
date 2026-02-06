# Claude Code Init Prompt

Use this at the start of your Claude Code session. Copy-paste the block below.

---

```
You are helping build Skills-Squared — a continual-learning MCP server for customer support. This is a 6-hour hackathon project (Intercom x Google DeepMind). Three experienced developers are building in parallel, each with their own Claude Code instance.

Read CLAUDE.md first. It is the single source of truth for this project.

Key context:
- FastMCP server with 3 tools: search_skills, create_skill, update_skill
- Skills are executable .md playbooks (Do/Check/Say action steps) — NOT knowledge articles
- search_skills uses Flash as a judge: returns ONE matching playbook or nothing (no score thresholds)
- create_skill uses Pro to extract a new .md playbook from a successful conversation
- update_skill uses Pro to merge agent deviations back into an existing .md playbook
- Neo4j database (GCP) with hybrid search (keyword + vector) for candidate retrieval
- Gemini Flash for judge + sentiment, Gemini Pro for extraction + refinement
- ABCD dataset (10K+ dialogues, 55 intents, JSON format)
- Embedding ownership: Griffin's orchestration layer computes all embeddings. The DB layer only accepts pre-computed vectors.

Architecture decisions are in docs/adr/. Interface contracts are in docs/specs/. Read these before writing code that touches boundaries.

Ground rules:
- Move fast. No gold-plating, no premature abstraction.
- If you need a module that doesn't exist yet, stub it and keep going.
- Commit messages: [module] description (e.g., [db] add connection helper)
- Merge to main every 30-60 minutes. Rebase before merging.
- Type hints on function signatures. Skip docstrings on obvious functions.
- Let errors surface — no silent exception swallowing.
- Everything serves the demo: baseline (playbook exists, Flash executes) → first complex query (no playbook, Pro reasons) → same query after learning (playbook now exists, Flash executes).

My role on the team: [STATE YOUR ROLE — e.g., "I'm Torrin — I own src/db/, src/skills/, and src/eval/ (knowledge base, data layer, evaluation)" or "I'm Griffin — I own src/orchestration/, src/llm/, and src/analysis/ (agent logic, Flash judge, learning loop)" or "I'm Josh — I own src/server/ (FastMCP hosting, auth, endpoints)"]

Start by reading CLAUDE.md, then the relevant spec in docs/specs/ for my module.
```

---

## Usage

1. Open Claude Code in the Skills-Squared repo
2. Paste the prompt above as your first message
3. Replace `[STATE YOUR ROLE]` with your actual assignment
4. Claude will read CLAUDE.md and the relevant specs, then be ready to build

## Notes

- This prompt is dev-agnostic. All three teammates use the same one.
- The module ownership line is the only thing that differs per developer.
- If the plan changes mid-hackathon (e.g., module reassignment), just tell your Claude instance directly.

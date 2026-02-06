# MCP Tools Specification

Interface contracts for the three core tools. Skills are executable `.md` playbooks with Do/Check/Say action steps — not knowledge articles. See `skill_schema_spec.md` for the full schema.

## 1. Search Skills

Find the best matching playbook for a customer query, or return nothing.

### Request

```python
class SearchRequest(BaseModel):
    query: str            # Customer's question or issue description
```

### Internal Pipeline (not exposed to the calling agent)

```python
# These params are internal to the search pipeline
TOP_K = 5               # Candidates fetched from Neo4j
```

### Response

```python
class SearchResponse(BaseModel):
    skill: SkillMatch | None  # Best match, or None if no playbook fits
    query: str                # Echo back the original query
    search_time_ms: float     # For benchmarking

class SkillMatch(BaseModel):
    skill_id: str         # UUID (application-generated)
    title: str            # Human-readable skill title
    confidence: float     # Historical success rate (0-1)
    resolution_md: str    # The full .md playbook (Do/Check/Say steps)
    conditions: list[str] # When this skill applies
```

### Flow

```
Agent → tools/call "search_skills" → Server [Josh]
  → Orchestration [Griffin] computes query embedding
  → db.hybrid_search(query_embedding, query_text, top_k=5) [Torrin]
  → Neo4j returns top candidates
  → Flash judge evaluates: "Does any playbook solve this?" [Griffin]
  → If match: return SkillMatch (one playbook)
  → If no match: return skill=None
```

### Notes
- The Flash judge makes the matching decision, not a score threshold
- The judge sees each candidate's title, problem, conditions, and confidence
- The agent receives ONE playbook to execute, or nothing — no ranked list
- Hybrid search (keyword + vector) narrows candidates; the judge picks the winner
- Query embedding is computed by the orchestration layer — the DB layer only accepts pre-computed vectors

---

## 2. Create Skill

Extract a new `.md` playbook from a successful support conversation.

### Request

```python
class CreateRequest(BaseModel):
    conversation: str     # Full conversation transcript
    resolution_confirmed: bool = False  # Was the resolution explicitly confirmed?
    metadata: dict = {}   # Optional: product area, issue type, customer segment
```

### Response

```python
class CreateResponse(BaseModel):
    skill_id: str         # UUID (application-generated) of the created skill
    title: str            # Generated title
    skill: dict           # Full skill document (see skill_schema_spec.md)
    created: bool         # True if new, False if duplicate detected
```

### Flow

```
Agent → tools/call "create_skill" → Server [Josh]
  → llm.extract_skill(conversation) [Griffin, Gemini Pro]
  → Pro returns structured .md playbook with Do/Check/Say steps
  → db.check_duplicate(skill.embedding, threshold=0.95) [Torrin]
  → If duplicate: return existing skill with created=False
  → If new: db.create_skill(skill) [Torrin]
  → Return CreateResponse
```

### Notes
- Skill extraction uses Gemini Pro — this is the expensive call the learning loop eliminates over time
- Pro generates the `.md` playbook in the Do/Check/Say format defined in `skill_schema_spec.md`
- Duplicate detection is approximate (vector similarity > 0.95 threshold)
- The `metadata` field is optional — Pro will infer what it can from the conversation

---

## 3. Update Skill

Refine an existing playbook with learnings from a conversation where the agent deviated.

### Request

```python
class UpdateRequest(BaseModel):
    skill_id: str         # ID of the skill to update
    conversation: str     # Conversation where agent deviated from the playbook
    feedback: str = ""    # What the agent changed and why
```

### Response

```python
class UpdateResponse(BaseModel):
    skill_id: str         # Same ID
    title: str            # Possibly updated title
    changes: list[str]    # Human-readable list of what changed in the .md
    version: int          # Incremented version number
```

### Flow

```
Agent → tools/call "update_skill" → Server [Josh]
  → db.get_skill(skill_id) [Torrin]
  → llm.refine_skill(existing_skill, conversation, feedback) [Griffin, Gemini Pro]
  → Pro merges agent's deviations into the .md playbook
  → db.update_skill(skill_id, updates: SkillUpdate) [Torrin]
  → Return UpdateResponse
```

### Notes
- Updates are additive — Pro merges new steps, edge cases, corrections into the existing `.md`
- The `changes` list is for human consumption (demo, logging)
- Version number is a simple integer counter
- If skill_id doesn't exist, return 404

---

## Error Handling

All tools return standard MCP errors via `isError: true` with actionable messages:

| Situation | Error Message |
|-----------|--------------|
| No query provided | `"query is required"` |
| Skill not found | `"Skill sk_123 not found. Use search_skills to find the correct ID."` |
| Neo4j down | `"Database connection failed: timeout after 5s"` |
| LLM failure | `"Gemini API error: {detail}. Retry or resolve from scratch."` |

Keep error messages specific so the LLM can self-correct and retry.

---

## DB Layer Contracts (`src/db/queries.py`)

Canonical function signatures — code and docs must match these:

```python
async def hybrid_search(
    query_embedding: list[float],   # Pre-computed by orchestration layer
    query_text: str,                # Raw text for keyword search
    top_k: int = 5,
) -> list[dict]:                    # [{"skill": Skill, "score": float}]

async def create_skill(skill: Skill) -> Skill

async def get_skill(skill_id: str) -> Skill | None

async def update_skill(skill_id: str, updates: SkillUpdate) -> Skill
    # Applies partial updates, increments version. Raises ValueError if not found.

async def check_duplicate(
    embedding: list[float],         # Pre-computed by orchestration layer
    threshold: float = 0.95,
) -> Skill | None                   # Returns existing skill if similarity > threshold
```

The DB layer never computes embeddings — it only accepts pre-computed vectors from the orchestration layer.

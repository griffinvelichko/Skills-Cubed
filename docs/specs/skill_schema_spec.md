# Skill Schema Specification

A "skill" is an **executable playbook for an AI agent**. It is NOT a knowledge article or canned response for the customer. A skill tells the agent exactly what actions to take, what APIs to call, what conditions to check, and what to communicate to the customer at each step. The goal: Gemini Flash can execute a known playbook instead of Gemini Pro having to figure out the playbook from scratch.

Skills are written as **structured natural language in markdown format**. The agent reads the skill internally and executes it — the customer never sees the skill document.

## Schema

```python
class Skill(BaseModel):
    # Identity
    skill_id: str             # UUID, generated on creation
    title: str                # Short, descriptive title (e.g., "Password Reset for Standard Users")
    version: int = 1          # Incremented on each update

    # Content
    problem: str              # What issue does this skill address?
    resolution_md: str        # Markdown playbook: agent-directed actions (see "Skill Markdown Format" below)
    conditions: list[str]     # When does this skill apply? (e.g., ["user is on enterprise plan", "SSO is enabled"])
    keywords: list[str]       # Explicit keyword tags for BM25 search

    # Embeddings
    embedding: list[float]    # Vector embedding of problem + conditions + keywords (NOT resolution — users search by problem, not solution)

    # Metadata
    product_area: str = ""    # e.g., "billing", "authentication", "onboarding"
    issue_type: str = ""      # e.g., "how-to", "bug", "feature-request", "escalation"
    confidence: float = 0.5   # 0-1, increases with successful uses and positive feedback
    times_used: int = 0       # How many times this skill was returned by search
    times_confirmed: int = 0  # How many times use led to confirmed resolution

    # Timestamps
    created_at: str           # ISO 8601
    updated_at: str           # ISO 8601
```

## Skill Markdown Format

The `resolution_md` field contains a markdown document written **for the agent, not the customer**. It uses structured natural language so any LLM can interpret and execute it without a custom parser or DSL.

A skill `.md` follows this structure:

```markdown
# [Skill Title]

**Confidence:** 0.85 (23 uses, 20 confirmed)
**Product Area:** billing
**Issue Type:** how-to

## Goal
One-sentence description of what this skill accomplishes.

## Prerequisites
- Conditions that must be true before executing (maps to `conditions` field)
- e.g., "Customer has a verified email on file"

## Steps

### 1. [Action description]
**Do:** [What the agent should do — API call, lookup, calculation, etc.]
**Check:** [What to verify before proceeding]
**Say:** [What to tell the customer, if anything]

### 2. [Action description]
**Do:** [Next action]
**Check:** [Verification]
**Say:** [Customer communication]

...

## Edge Cases
- [Condition] → [What to do instead]
- [Condition] → [Escalation instruction]

## Escalation
When to stop and hand off to a human, and what context to pass along.
```

The confidence header tells the agent how much to trust this playbook. A skill at 0.9 can be followed mechanically. A skill at 0.5 should be treated as a starting point — the agent should verify each step and be ready to deviate.

The `Do/Check/Say` pattern gives the agent clear, separable instructions:
- **Do** = internal action (API call, data lookup, calculation)
- **Check** = gate before proceeding (condition, validation, error check)
- **Say** = customer-facing communication

This is structured enough for Flash to follow mechanically, but flexible enough that Pro can generate it from messy conversation transcripts.

## Neo4j Node Structure

```cypher
(:Skill {
    skill_id: "uuid-here",
    title: "Password Reset for Standard Users",
    version: 1,
    problem: "Customer cannot log in and wants to reset their password",
    resolution_md: "# Password Reset for Standard Users\n\n**Confidence:** 0.75 ...",  // full .md playbook
    conditions: ["user is NOT on SSO/enterprise plan", "user has a verified email on file"],
    keywords: ["password", "reset", "login", "locked out"],
    embedding: [0.123, -0.456, ...],  // vector index (embeds problem + conditions + keywords, NOT resolution)
    product_area: "authentication",
    issue_type: "how-to",
    confidence: 0.75,
    times_used: 12,
    times_confirmed: 9,
    created_at: "2026-02-05T10:30:00Z",
    updated_at: "2026-02-05T14:15:00Z"
})
```

## Vector Index

```cypher
CREATE VECTOR INDEX skill_embedding IF NOT EXISTS
FOR (s:Skill)
ON (s.embedding)
OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
}}
```

Embedding dimension is configurable via `EMBEDDING_DIM` env var (default: 768, Gemini embedding model).

**Validation**: A Pydantic `model_validator` on `Skill` enforces that `embedding` is non-empty and has length == `EMBEDDING_DIM` on every construction path (including `create_new()`, `from_neo4j_node()`, and direct construction). `src/utils/config.py` provides `validate_embedding()` as a standalone check for use at other boundaries (e.g., `hybrid_search()` must validate `query_embedding` when implemented).

## Full-Text Index

```cypher
CREATE FULLTEXT INDEX skill_keywords IF NOT EXISTS
FOR (n:Skill)
ON EACH [n.title, n.problem, n.resolution_md, n.keywords]
```

## Hybrid Search Query

```cypher
// Vector search
CALL db.index.vector.queryNodes('skill_embedding', $top_k, $query_embedding)
YIELD node, score AS vector_score

// Full-text search (in parallel or as fallback)
CALL db.index.fulltext.queryNodes('skill_keywords', $query_text)
YIELD node, score AS keyword_score

// Combine scores (simple weighted average)
// weight_vector = 0.7, weight_keyword = 0.3
```

The exact hybrid scoring formula can be tuned. Start with 70/30 vector/keyword and adjust based on demo results.

### Score Normalization

1. **Vector scores**: Use raw Neo4j vector score as returned (typically [0,1] for cosine). If runtime returns out-of-range values, clamp to [0,1]. Add a smoke test that logs observed score range on first search to catch version/config surprises.
2. **Keyword scores (BM25/fulltext)**: Min-max normalize within result set: `(score - min) / (max - min)`
   - Edge case: if `max == min` (all scores identical), all normalized scores = 1.0
   - Edge case: if only 1 result, normalized keyword score = 1.0
3. **Combined**: `0.7 * norm_vector + 0.3 * norm_keyword`
4. **Clamp** final score to [0.0, 1.0]
5. **min_score filter** is applied AFTER combining and clamping — results below min_score are dropped from the response

## Confidence Scoring

Confidence starts at 0.5 (neutral) and adjusts based on resolution outcomes:
- **+0.10** on confirmed resolution (`times_confirmed++`)
- **+0.03** on likely resolution (positive signals but no explicit confirmation)
- **-0.05** on likely failure (negative signals)
- **-0.10** on confirmed failure (explicit negative feedback or escalation)
- **+0.01** on use without feedback (slight positive bias for being selected)
- Clamped to [0.0, 1.0]

The confidence score is embedded in the skill's `.md` header so the LLM-as-judge can
factor it into routing decisions. A skill with confidence < 0.3 has failed often and the
judge should treat it skeptically. The confidence score also tells the executing agent
how much to trust the playbook — high confidence means follow mechanically, low
confidence means verify each step.

This is a simple heuristic. Good enough for the demo. Don't over-engineer the scoring formula.

## Skill Lifecycle

```
Conversation → Pro reasons from scratch → Customer satisfied
    → create_skill → Pro extracts .md playbook → Create Skill (confidence=0.5)
    → Flash judge returns skill on future queries → times_used++
        → Customer satisfied, no deviation → CONFIRM → times_confirmed++, confidence++
        → Customer satisfied, agent deviated → UPDATE → Pro refines .md, version++
        → Customer unsatisfied → DOWNGRADE → confidence--
```

## Example Skill Document

```json
{
    "skill_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "title": "Resolve Billing Discrepancy for Annual Plan Downgrade",
    "version": 2,
    "problem": "Customer was charged the full annual rate after downgrading mid-cycle. They expect a prorated refund for the remaining months.",
    "resolution_md": "see below",
    "conditions": [
        "customer is on annual plan",
        "downgrade occurred mid-billing-cycle",
        "customer requests refund"
    ],
    "keywords": ["billing", "refund", "downgrade", "annual", "prorated"],
    "embedding": [0.123, -0.456, "...768 floats..."],
    "product_area": "billing",
    "issue_type": "how-to",
    "confidence": 0.75,
    "times_used": 8,
    "times_confirmed": 6,
    "created_at": "2026-02-05T10:30:00Z",
    "updated_at": "2026-02-05T14:15:00Z"
}
```

### Example `resolution_md` Content

This is what the agent reads and executes. The customer never sees this.

```markdown
# Resolve Billing Discrepancy for Annual Plan Downgrade

**Confidence:** 0.75 (8 uses, 6 confirmed)
**Product Area:** billing
**Issue Type:** how-to

## Goal
Issue a prorated refund for a customer who was overcharged after downgrading their annual plan mid-cycle.

## Prerequisites
- Customer is on an annual billing plan
- A downgrade occurred mid-billing-cycle
- Customer is requesting a refund

## Steps

### 1. Look up the downgrade date
**Do:** Call GET /api/billing/subscriptions/{customer_id} → find the `downgrade_date` field
**Check:** Confirm `downgrade_date` exists and is within the current billing cycle
**Say:** "Let me pull up your billing details now."

### 2. Calculate the prorated refund
**Do:** remaining_months = months between downgrade_date and cycle_end. refund = (remaining_months / 12) * annual_rate
**Check:** refund amount is > $0 and less than the full annual charge
**Say:** Nothing yet — confirm the number before telling the customer.

### 3. Issue the refund
**Do:** Call POST /api/billing/refunds with { customer_id, amount, reason: "prorated_downgrade" }
**Check:** Response status is 200 and refund_id is returned
**Say:** "I've issued a refund of ${amount} to your original payment method. You should see it within 3-5 business days."

### 4. Confirm with customer
**Do:** Nothing — wait for customer acknowledgment
**Check:** Customer confirms they understand the timeline
**Say:** "Is there anything else I can help you with?"

## Edge Cases
- Downgrade was > 30 days ago → escalate to billing manager, do not issue refund directly
- Refund API returns error → tell customer "I'm escalating this to our billing team" and create an internal ticket
- Customer disputes the prorated amount → walk through the calculation transparently, show the math

## Escalation
If the refund amount exceeds $500 or the downgrade is older than 30 days, hand off to a billing manager with: customer_id, downgrade_date, calculated refund amount, and conversation transcript.
```

## What NOT To Over-Engineer

- Don't add skill categories, tags, or hierarchies beyond `product_area` and `issue_type`
- Don't build a skill versioning system with diffs — just overwrite and increment version
- Don't add relationships between skills (e.g., "prerequisite") during the hackathon — the graph supports it later
- Don't validate every field on every operation — trust the LLM output for now, validate at boundaries

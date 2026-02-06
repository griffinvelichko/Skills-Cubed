import json
import time

from src.db import queries as db
from src.llm.client import call_flash, embed
from src.server.models import SearchResponse, SkillMatch

JUDGE_PROMPT = """\
You are a routing judge for a customer support system. Given a customer query and a list of candidate skill playbooks, decide which ONE skill best matches the query — or return "none" if no skill is a good fit.

CUSTOMER QUERY:
{query}

CANDIDATE SKILLS:
{candidates}

Rules:
- Pick the single best match. Do not pick multiple.
- A skill is a match if it addresses the customer's core issue AND the conditions are compatible.
- If no skill is a good fit, return "none". Do not force a match.
- Consider the confidence score — a skill with very low confidence (<0.3) should be treated skeptically.

Return JSON with exactly one field:
{{"skill_id": "<the chosen skill_id, or \\"none\\">"}}

Return ONLY valid JSON, no markdown fences.
"""


def _format_candidates(candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        skill = c["skill"]
        lines.append(
            f"- skill_id: {skill.skill_id}\n"
            f"  title: {skill.title}\n"
            f"  problem: {skill.problem}\n"
            f"  conditions: {skill.conditions}\n"
            f"  confidence: {skill.confidence}"
        )
    return "\n".join(lines)


async def search_skills_orchestration(query: str) -> SearchResponse:
    start = time.monotonic()

    query_embedding = await embed(query, task_type="RETRIEVAL_QUERY")
    candidates = await db.hybrid_search(query_embedding, query, top_k=5)

    if not candidates:
        elapsed = (time.monotonic() - start) * 1000
        return SearchResponse(skill=None, query=query, search_time_ms=elapsed)

    formatted = _format_candidates(candidates)
    judge_prompt = JUDGE_PROMPT.format(query=query, candidates=formatted)
    judge_response = await call_flash(judge_prompt)
    result = json.loads(judge_response)

    chosen_id = result.get("skill_id", "none")

    if chosen_id == "none":
        elapsed = (time.monotonic() - start) * 1000
        return SearchResponse(skill=None, query=query, search_time_ms=elapsed)

    chosen_skill = None
    for c in candidates:
        if c["skill"].skill_id == chosen_id:
            chosen_skill = c["skill"]
            break

    if chosen_skill is None:
        elapsed = (time.monotonic() - start) * 1000
        return SearchResponse(skill=None, query=query, search_time_ms=elapsed)

    match = SkillMatch(
        skill_id=chosen_skill.skill_id,
        title=chosen_skill.title,
        confidence=chosen_skill.confidence,
        resolution_md=chosen_skill.resolution_md,
        conditions=chosen_skill.conditions,
    )

    elapsed = (time.monotonic() - start) * 1000
    return SearchResponse(skill=match, query=query, search_time_ms=elapsed)

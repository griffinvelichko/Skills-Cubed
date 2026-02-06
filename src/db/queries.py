import re
from datetime import datetime, timezone

from src.db.connection import get_driver
from src.skills.models import Skill, SkillUpdate
from src.utils.config import validate_embedding

# Lucene special characters that must be escaped for fulltext queries
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}[\]^"~*?:\\/@])')


def _escape_lucene(text: str) -> str:
    """Escape Lucene special characters so raw user text is safe for fulltext search."""
    return _LUCENE_SPECIAL.sub(r'\\\1', text)


async def get_skill(skill_id: str) -> Skill | None:
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (s:Skill {skill_id: $skill_id}) RETURN properties(s) AS props",
            skill_id=skill_id,
        )
        record = await result.single(strict=False)
        if record is None:
            return None
        return Skill.from_neo4j_node(dict(record["props"]))


async def create_skill(skill: Skill) -> Skill:
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            "CREATE (s:Skill) SET s = $props RETURN properties(s) AS props",
            props=skill.to_neo4j_props(),
        )
        record = await result.single()
        return Skill.from_neo4j_node(dict(record["props"]))


async def check_duplicate(embedding: list[float], threshold: float = 0.95) -> Skill | None:
    validate_embedding(embedding, context="check_duplicate")
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            CALL db.index.vector.queryNodes('skill_embedding', 1, $embedding)
            YIELD node, score
            RETURN properties(node) AS props, score
            """,
            embedding=embedding,
        )
        record = await result.single(strict=False)
        if record is None:
            return None
        if record["score"] > threshold:
            return Skill.from_neo4j_node(dict(record["props"]))
        return None


async def update_skill(skill_id: str, updates: SkillUpdate) -> Skill:
    if updates.embedding is not None:
        validate_embedding(updates.embedding, context="update_skill")

    changes = {k: v for k, v in updates.model_dump().items() if v is not None}
    updated_at = datetime.now(timezone.utc).isoformat()

    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Skill {skill_id: $skill_id})
            SET s += $changes, s.version = s.version + 1, s.updated_at = $updated_at
            RETURN properties(s) AS props
            """,
            skill_id=skill_id,
            changes=changes,
            updated_at=updated_at,
        )
        record = await result.single(strict=False)
        if record is None:
            raise ValueError(f"Skill {skill_id} not found")
        return Skill.from_neo4j_node(dict(record["props"]))


async def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[dict]:
    """Search skills by combined vector + keyword similarity.

    Returns list of dicts with keys: skill (Skill), score (float).
    Score is normalized to [0, 1].
    """
    validate_embedding(query_embedding, context="hybrid_search")
    fetch_count = top_k * 2

    driver = await get_driver()
    async with driver.session() as session:
        # Vector search
        vec_result = await session.run(
            """
            CALL db.index.vector.queryNodes('skill_embedding', $fetch_count, $embedding)
            YIELD node, score
            RETURN properties(node) AS props, score
            """,
            fetch_count=fetch_count,
            embedding=query_embedding,
        )
        vec_records = await vec_result.values()

        # Fulltext search (skip if query_text is empty/whitespace)
        kw_records = []
        has_keyword = query_text and query_text.strip()
        if has_keyword:
            kw_result = await session.run(
                """
                CALL db.index.fulltext.queryNodes('skill_keywords', $query_text)
                YIELD node, score
                RETURN properties(node) AS props, score
                LIMIT $fetch_count
                """,
                query_text=_escape_lucene(query_text.strip()),
                fetch_count=fetch_count,
            )
            kw_records = await kw_result.values()

    return _merge_scores(vec_records, kw_records, min_score, top_k)


def _merge_scores(
    vec_records: list,
    kw_records: list,
    min_score: float,
    top_k: int,
) -> list[dict]:
    """Pure scoring logic — merge vector + keyword results into ranked list.

    Extracted from hybrid_search so edge cases can be unit-tested without Neo4j.
    Weighting is based on whether kw_records actually contains results, not on
    whether a keyword query was attempted — avoids the 0.7 cap when fulltext
    returns zero rows for a non-empty query_text.
    """
    # Build score maps keyed by skill_id
    vec_scores: dict[str, tuple[dict, float]] = {}
    for props, score in vec_records:
        props = dict(props) if not isinstance(props, dict) else props
        sid = props["skill_id"]
        # Clamp vector score to [0, 1]
        vec_scores[sid] = (props, max(0.0, min(1.0, score)))

    kw_scores: dict[str, tuple[dict, float]] = {}
    if kw_records:
        raw_kw = [(dict(p) if not isinstance(p, dict) else p, s) for p, s in kw_records]
        kw_max = max(s for _, s in raw_kw)
        kw_min = min(s for _, s in raw_kw)
        kw_range = kw_max - kw_min
        for props, score in raw_kw:
            sid = props["skill_id"]
            normalized = (score - kw_min) / kw_range if kw_range > 0 else 1.0
            kw_scores[sid] = (props, normalized)

    has_keyword_results = bool(kw_scores)

    # Merge — collect all skill_ids from both result sets
    all_ids = set(vec_scores.keys()) | set(kw_scores.keys())
    combined: list[dict] = []

    for sid in all_ids:
        v_score = vec_scores[sid][1] if sid in vec_scores else 0.0
        k_score = kw_scores[sid][1] if sid in kw_scores else 0.0
        props = vec_scores[sid][0] if sid in vec_scores else kw_scores[sid][0]

        if has_keyword_results:
            final = 0.7 * v_score + 0.3 * k_score
        else:
            final = v_score

        final = max(0.0, min(1.0, final))

        if final >= min_score:
            combined.append({"skill": Skill.from_neo4j_node(props), "score": final})

    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined[:top_k]

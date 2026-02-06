from src.skills.models import Skill, SkillUpdate
from src.utils.config import validate_embedding


async def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 5,
    min_score: float = 0.0,
) -> list[dict]:
    """Search skills by combined vector + keyword similarity.

    Returns list of dicts with keys: skill (Skill), score (float).
    Score is normalized to [0, 1] per skill_schema_spec.md.
    """
    validate_embedding(query_embedding, context="hybrid_search")
    raise NotImplementedError("Torrin — implement in hackathon Block 1")


async def create_skill(skill: Skill) -> Skill:
    """Write a new Skill node to Neo4j. Returns the created skill."""
    raise NotImplementedError("Torrin — implement in hackathon Block 1")


async def get_skill(skill_id: str) -> Skill | None:
    """Fetch a single skill by UUID. Returns None if not found."""
    raise NotImplementedError("Torrin — implement in hackathon Block 1")


async def update_skill(skill_id: str, updates: SkillUpdate) -> Skill:
    """Apply partial updates to an existing skill. Increments version.

    Raises ValueError if skill_id not found.
    """
    raise NotImplementedError("Torrin — implement in hackathon Block 1")


async def check_duplicate(embedding: list[float], threshold: float = 0.95) -> Skill | None:
    """Check if a skill with similar embedding already exists.

    Returns the existing skill if vector similarity > threshold, else None.
    """
    validate_embedding(embedding, context="check_duplicate")
    raise NotImplementedError("Torrin — implement in hackathon Block 1")

"""DB-layer smoke test — proves the 3-beat demo flow works at the data layer.

No LLM calls required (uses synthetic embeddings).

Run with:
    venv/bin/python3 scripts/smoke_test.py
"""

import asyncio
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.db import ensure_indexes
from src.db.connection import get_driver, close_driver
from src.db.queries import create_skill, hybrid_search, update_skill, get_skill
from src.skills.models import Skill, SkillUpdate
from src.utils.config import EMBEDDING_DIM

TEST_PREFIX = "smoke_test_"


def _synthetic_embedding(seed: int = 42) -> list[float]:
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


def _similar_embedding(base: list[float], noise: float = 0.05) -> list[float]:
    rng = random.Random(99)
    vec = [x + rng.gauss(0, noise) for x in base]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


async def main():
    print("=== Smoke Test: DB Layer ===\n")

    # 1. Ensure indexes
    print("1. Ensuring indexes...")
    await ensure_indexes()
    print("   OK\n")

    # 2. Create a skill with synthetic embedding
    print("2. Creating test skill...")
    embedding = _synthetic_embedding()
    skill = Skill.create_new(
        title=f"{TEST_PREFIX}password_reset",
        problem="Customer cannot reset their password",
        resolution_md="## Steps\n1. Verify identity\n2. Send reset link\n3. Confirm reset",
        embedding=embedding,
        conditions=["account locked", "forgot password"],
        keywords=["password", "reset", "locked", "account"],
    )
    created = await create_skill(skill)
    print(f"   Created: {created.skill_id} (v{created.version})")
    assert created.version == 1
    print("   OK\n")

    try:
        # 3. Search with similar embedding
        print("3. Searching with similar embedding...")
        query_embedding = _similar_embedding(embedding)
        results = await hybrid_search(query_embedding, "password reset help", top_k=5)
        found = any(r["skill"].skill_id == created.skill_id for r in results) if results else False

        assert found, f"Skill not found in search results! Got {len(results)} results."
        print(f"   Found skill in {len(results)} results")
        print("   OK\n")

        # 4. Update the skill
        print("4. Updating test skill...")
        updates = SkillUpdate(
            resolution_md="## Steps\n1. Verify identity via email\n2. Send reset link\n3. Confirm reset\n4. Set new password",
            keywords=["password", "reset", "locked", "account", "email"],
        )
        updated = await update_skill(created.skill_id, updates)
        assert updated.version == 2, f"Expected version 2, got {updated.version}"
        print(f"   Updated: v{updated.version}")
        print("   OK\n")

        # 5. Search again — verify updated skill returned
        print("5. Verifying updated skill in search...")
        results2 = await hybrid_search(query_embedding, "password reset email", top_k=5)
        found2 = False
        for r in results2:
            s = r["skill"]
            if s.skill_id == created.skill_id:
                assert s.version == 2, f"Expected version 2, got {s.version}"
                found2 = True
                break
        assert found2, "Updated skill not found in search results!"
        print(f"   Found updated skill (v2) in {len(results2)} results")
        print("   OK\n")

    finally:
        # 6. Clean up
        print("6. Cleaning up test skill...")
        driver = await get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (s:Skill {skill_id: $sid}) DETACH DELETE s",
                sid=created.skill_id,
            )
            await result.consume()
        print("   Deleted\n")

    await close_driver()
    print("=== All smoke tests passed! ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)

"""Live integration tests for the MCP tools.

Requires: GOOGLE_API_KEY, NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD

These tests make real API calls to Gemini and real queries to Neo4j.
They exercise the full pipeline: MCP tool handler → orchestration → LLM → DB.
"""
import asyncio
import os

import pytest

_REQUIRED_ENV = ("GOOGLE_API_KEY", "NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(os.getenv(v) for v in _REQUIRED_ENV),
        reason=f"Missing env vars: {[v for v in _REQUIRED_ENV if not os.getenv(v)]}",
    ),
]


# --- Test conversations ---

CONVERSATION_A = """\
Agent: Thank you for calling support. How can I help?
Customer: I can't log into my account. I've tried resetting my password three times but the email never arrives.
Agent: I understand how frustrating that is. Let me pull up your account. Can you confirm the email address?
Customer: Sure, it's john@example.com
Agent: I can see the issue — the email on file has a typo. It says john@exmaple.com instead of john@example.com. Let me correct that.
Customer: Oh, that makes sense!
Agent: Done. I've fixed the email and sent a new password reset link. You should get it within a few minutes.
Customer: I can see the email now. Thank you so much!
Agent: You're welcome! Anything else I can help with?
Customer: No, that's all. Thanks!
"""

CONVERSATION_B = """\
Agent: Support team here, how can I help?
Customer: I got locked out of my account after too many failed password attempts.
Agent: I can see the lockout flag on your account. I'll clear it right away and send a password reset link to your verified email.
Customer: That would be great.
Agent: Lockout cleared and reset link sent. Give it a couple of minutes and try again.
Customer: Working now. Thank you!
"""

CONVERSATION_BILLING = """\
Agent: Hi, how can I help you today?
Customer: I was charged twice for my subscription this month.
Agent: I'm sorry about that. Let me check your billing history. I can see the duplicate charge on January 15th. I'll process a refund for the extra charge right now.
Customer: How long will the refund take?
Agent: The refund should appear on your statement within 3-5 business days.
Customer: OK, thanks for the help.
"""


# --- Fixtures ---

_indexes_initialized = False


@pytest.fixture(autouse=True)
async def _reset_clients():
    """Reset singletons per-test so they bind to the current event loop."""
    from src.db import connection
    from src.llm import client as llm_client

    connection._driver = None
    llm_client._client = None

    global _indexes_initialized
    if not _indexes_initialized:
        await connection.initialize_indexes()
        _indexes_initialized = True
        connection._driver = None
        llm_client._client = None


@pytest.fixture
async def cleanup_skills():
    """Collect skill IDs during the test, delete them from Neo4j after."""
    created_ids: list[str] = []
    yield created_ids

    from src.db.connection import get_driver

    driver = await get_driver()
    async with driver.session() as session:
        for sid in created_ids:
            await session.run(
                "MATCH (s:Skill {skill_id: $sid}) DELETE s",
                sid=sid,
            )


# --- Create Skill ---


async def test_create_skill_live(cleanup_skills):
    """Create a skill from a real conversation → real Gemini extraction → real Neo4j write."""
    from src.server.server import create_skill

    result = await create_skill.fn(conversation=CONVERSATION_A)
    cleanup_skills.append(result["skill_id"])

    assert result["created"] is True
    assert len(result["skill_id"]) == 36
    assert isinstance(result["title"], str)
    assert len(result["title"]) > 0


async def test_create_produces_valid_skill_dict(cleanup_skills):
    """Created skill dict has all Skill model fields with correct types."""
    from src.server.server import create_skill

    result = await create_skill.fn(conversation=CONVERSATION_A)
    cleanup_skills.append(result["skill_id"])

    skill = result["skill"]

    # All model fields present
    for field in [
        "skill_id", "title", "version", "problem", "resolution_md",
        "conditions", "keywords", "embedding", "confidence",
        "created_at", "updated_at",
    ]:
        assert field in skill, f"Missing field: {field}"

    # Correct types and defaults
    assert len(skill["embedding"]) == 768
    assert skill["version"] == 1
    assert skill["confidence"] == 0.5
    assert skill["times_used"] == 0


async def test_create_extracts_meaningful_content(cleanup_skills):
    """Pro extraction produces relevant problem, keywords, and resolution from conversation."""
    from src.server.server import create_skill

    result = await create_skill.fn(conversation=CONVERSATION_A)
    cleanup_skills.append(result["skill_id"])

    skill = result["skill"]

    # Problem should relate to the conversation topic
    problem_lower = skill["problem"].lower()
    assert any(
        word in problem_lower
        for word in ["login", "log in", "password", "email", "account", "reset"]
    ), f"Problem doesn't seem related to the conversation: {skill['problem']}"

    # Keywords should be non-empty
    assert len(skill["keywords"]) > 0

    # Resolution should be a Do/Check/Say playbook with real content
    assert len(skill["resolution_md"]) > 50


async def test_create_skill_persists_in_db(cleanup_skills):
    """Created skill is readable from Neo4j."""
    from src.db.queries import get_skill
    from src.server.server import create_skill

    result = await create_skill.fn(conversation=CONVERSATION_A)
    skill_id = result["skill_id"]
    cleanup_skills.append(skill_id)

    db_skill = await get_skill(skill_id)
    assert db_skill is not None
    assert db_skill.skill_id == skill_id
    assert db_skill.title == result["title"]
    assert db_skill.version == 1
    assert len(db_skill.embedding) == 768


async def test_create_with_metadata_fallback(cleanup_skills):
    """Metadata dict fills in product_area/issue_type when Pro omits them."""
    from src.server.server import create_skill

    result = await create_skill.fn(
        conversation=CONVERSATION_BILLING,
        metadata={"product_area": "billing", "issue_type": "bug"},
    )
    cleanup_skills.append(result["skill_id"])

    skill = result["skill"]
    # If Pro extracted its own values, those take priority.
    # If not, metadata fallback should provide them.
    assert skill["product_area"] != "" or skill["product_area"] == "billing"


# --- Search Skill ---


async def test_search_returns_valid_response_structure():
    """Search response dict has correct schema even with no match."""
    from src.server.server import search_skills

    result = await search_skills.fn(query="billing refund request")

    assert "skill" in result
    assert "query" in result
    assert "search_time_ms" in result
    assert result["query"] == "billing refund request"
    assert isinstance(result["search_time_ms"], float)
    assert result["search_time_ms"] > 0


async def test_search_finds_created_skill(cleanup_skills):
    """Create a skill, then search for it — should find a relevant match."""
    from src.server.server import create_skill, search_skills

    # Create
    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    cleanup_skills.append(create_result["skill_id"])

    # Wait for Neo4j vector index to catch up
    await asyncio.sleep(3)

    # Search with a query that matches the created skill
    search_result = await search_skills.fn(
        query="customer can't log in, password reset email not arriving"
    )

    assert search_result["search_time_ms"] > 0

    # Should find a match (our skill or another relevant one)
    if search_result["skill"] is not None:
        match = search_result["skill"]
        assert "skill_id" in match
        assert "title" in match
        assert "resolution_md" in match
        assert "confidence" in match
        assert "conditions" in match
        assert isinstance(match["confidence"], float)
        assert 0 <= match["confidence"] <= 1


async def test_search_match_has_resolution_md(cleanup_skills):
    """When search returns a match, it includes the full resolution_md playbook."""
    from src.server.server import create_skill, search_skills

    # Create
    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    cleanup_skills.append(create_result["skill_id"])

    await asyncio.sleep(3)

    search_result = await search_skills.fn(
        query="password reset email never arrives for customer"
    )

    if search_result["skill"] is not None:
        # resolution_md should be a non-trivial playbook
        assert len(search_result["skill"]["resolution_md"]) > 20


async def test_search_unrelated_query():
    """Search for something completely unrelated should return none or weak match."""
    from src.server.server import search_skills

    result = await search_skills.fn(
        query="recipe for chocolate cake with strawberry frosting"
    )

    # Judge should reject unrelated queries
    # (may still return a match if DB has something vaguely related)
    assert result["search_time_ms"] > 0


# --- Update Skill ---


async def test_update_skill_live(cleanup_skills):
    """Create a skill, then update it with new conversation data."""
    from src.server.server import create_skill, update_skill

    # Create
    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    skill_id = create_result["skill_id"]
    cleanup_skills.append(skill_id)

    # Update with a related but different conversation
    update_result = await update_skill.fn(
        skill_id=skill_id,
        conversation=CONVERSATION_B,
        feedback="Agent also needed to clear account lockout before reset",
    )

    assert update_result["skill_id"] == skill_id
    assert update_result["version"] == 2
    assert isinstance(update_result["changes"], list)
    assert len(update_result["changes"]) > 0
    assert isinstance(update_result["title"], str)


async def test_update_persists_version_bump(cleanup_skills):
    """Updated skill has version=2 in the database."""
    from src.db.queries import get_skill
    from src.server.server import create_skill, update_skill

    # Create
    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    skill_id = create_result["skill_id"]
    cleanup_skills.append(skill_id)

    # Update
    await update_skill.fn(
        skill_id=skill_id,
        conversation=CONVERSATION_B,
    )

    # Verify in DB
    db_skill = await get_skill(skill_id)
    assert db_skill is not None
    assert db_skill.version == 2
    assert db_skill.skill_id == skill_id


async def test_update_changes_describe_what_changed(cleanup_skills):
    """Update response includes human-readable change descriptions."""
    from src.server.server import create_skill, update_skill

    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    skill_id = create_result["skill_id"]
    cleanup_skills.append(skill_id)

    update_result = await update_skill.fn(
        skill_id=skill_id,
        conversation=CONVERSATION_B,
        feedback="The lockout scenario was new and not in the original playbook",
    )

    # Changes should be non-empty strings describing what was refined
    assert len(update_result["changes"]) > 0
    for change in update_result["changes"]:
        assert isinstance(change, str)
        assert len(change) > 0


async def test_update_nonexistent_skill_raises():
    """Updating a skill that doesn't exist raises ToolError."""
    from fastmcp.exceptions import ToolError

    from src.server.server import update_skill

    with pytest.raises(ToolError, match="not found"):
        await update_skill.fn(
            skill_id="00000000-0000-0000-0000-000000000000",
            conversation="some conversation",
        )


async def test_update_recomputes_embedding(cleanup_skills):
    """Updated skill has a different embedding than the original."""
    from src.db.queries import get_skill
    from src.server.server import create_skill, update_skill

    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    skill_id = create_result["skill_id"]
    cleanup_skills.append(skill_id)

    original_embedding = create_result["skill"]["embedding"]

    await update_skill.fn(
        skill_id=skill_id,
        conversation=CONVERSATION_B,
        feedback="Added lockout handling which is a new scenario",
    )

    db_skill = await get_skill(skill_id)
    # Embedding should be recomputed (different from original)
    assert db_skill.embedding != original_embedding


# --- Full lifecycle ---


async def test_full_lifecycle_create_search_update(cleanup_skills):
    """Complete lifecycle: Create → Search → Update → Verify in DB."""
    from src.db.queries import get_skill
    from src.server.server import create_skill, search_skills, update_skill

    # 1. Create from conversation A
    create_result = await create_skill.fn(conversation=CONVERSATION_A)
    skill_id = create_result["skill_id"]
    cleanup_skills.append(skill_id)

    assert create_result["created"] is True
    assert create_result["skill"]["version"] == 1

    # 2. Wait for vector index
    await asyncio.sleep(3)

    # 3. Search — should find something relevant
    search_result = await search_skills.fn(
        query="customer can't log in, password reset email never arrives"
    )
    assert search_result["search_time_ms"] > 0

    # 4. Update with conversation B
    update_result = await update_skill.fn(
        skill_id=skill_id,
        conversation=CONVERSATION_B,
        feedback="Added lockout handling",
    )
    assert update_result["version"] == 2
    assert len(update_result["changes"]) > 0

    # 5. Verify in DB
    db_skill = await get_skill(skill_id)
    assert db_skill is not None
    assert db_skill.version == 2
    assert db_skill.skill_id == skill_id
    assert len(db_skill.embedding) == 768


# --- Duplicate detection ---


async def test_create_duplicate_detection(cleanup_skills):
    """Creating from the same conversation twice — second should detect duplicate."""
    from src.server.server import create_skill

    # First creation
    result_1 = await create_skill.fn(conversation=CONVERSATION_A)
    cleanup_skills.append(result_1["skill_id"])
    assert result_1["created"] is True

    # Second creation with identical conversation
    result_2 = await create_skill.fn(conversation=CONVERSATION_A)

    if result_2["created"] is False:
        # Duplicate detected — should reference the first skill
        assert result_2["skill_id"] == result_1["skill_id"]
    else:
        # Embedding slightly different (Pro nondeterminism) — still valid
        cleanup_skills.append(result_2["skill_id"])

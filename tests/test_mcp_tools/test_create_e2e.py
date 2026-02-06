"""End-to-end tests for the create_skill MCP tool.

Tests the full pipeline: MCP tool handler → orchestration → mocked LLM + DB.
Only external boundaries (Gemini API, Neo4j) are mocked.
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.skills.models import Skill


EXTRACTED = {
    "title": "Password Reset",
    "problem": "Customer cannot log in",
    "resolution": "# Steps\n**Do:** Reset password",
    "conditions": ["user is locked out"],
    "keywords": ["password", "login"],
    "product_area": "auth",
    "issue_type": "how-to",
}


def _make_skill(**overrides) -> Skill:
    defaults = dict(
        skill_id="skill-001",
        title="Password Reset",
        version=1,
        problem="Customer cannot log in",
        resolution_md="# Steps\n**Do:** Reset password",
        conditions=["user is locked out"],
        keywords=["password", "login"],
        embedding=[0.1] * 768,
        product_area="auth",
        issue_type="how-to",
        confidence=0.5,
        times_used=0,
        times_confirmed=0,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Skill(**defaults)


# --- Happy path: full pipeline ---


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_full_pipeline_new_skill(mock_pro, mock_embed, mock_db):
    """Conversation → Pro extracts → embed → no duplicate → skill created → response dict."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="Agent: Hi\nCustomer: Can't log in")

    assert result["created"] is True
    assert result["title"] == "Password Reset"
    assert len(result["skill_id"]) == 36  # UUID format
    mock_db.create_skill.assert_awaited_once()


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_full_pipeline_duplicate_detected(mock_pro, mock_embed, mock_db):
    """Duplicate found → created=False, returns existing skill info."""
    existing = _make_skill()
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=existing)

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="Agent: Hi\nCustomer: Can't log in")

    assert result["created"] is False
    assert result["skill_id"] == "skill-001"
    assert result["title"] == "Password Reset"
    mock_db.create_skill.assert_not_called()


# --- Data flow verification ---


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_resolution_key_maps_to_resolution_md(
    mock_pro, mock_embed, mock_db
):
    """Pro returns 'resolution' key → stored as 'resolution_md' in Skill model."""
    mock_pro.return_value = EXTRACTED  # has "resolution" key, not "resolution_md"
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="conversation")

    assert "resolution_md" in result["skill"]
    assert result["skill"]["resolution_md"] == "# Steps\n**Do:** Reset password"


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_embed_text_excludes_resolution(mock_pro, mock_embed, mock_db):
    """Embedding text = problem + conditions + keywords. Resolution excluded."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    await create_skill.fn(conversation="conversation text")

    embed_text = mock_embed.call_args.args[0]
    assert "Customer cannot log in" in embed_text  # problem
    assert "user is locked out" in embed_text  # conditions
    assert "password" in embed_text  # keywords
    assert "**Do:**" not in embed_text  # resolution excluded


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_embeds_with_default_retrieval_document(
    mock_pro, mock_embed, mock_db
):
    """Stored skill embedding uses default RETRIEVAL_DOCUMENT (not RETRIEVAL_QUERY)."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    await create_skill.fn(conversation="conversation")

    # embed() called without explicit task_type → uses default RETRIEVAL_DOCUMENT
    mock_embed.assert_awaited_once()
    assert "task_type" not in mock_embed.call_args.kwargs


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_duplicate_check_uses_computed_embedding(
    mock_pro, mock_embed, mock_db
):
    """check_duplicate receives the embedding computed from extracted fields."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.5] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    await create_skill.fn(conversation="conversation")

    mock_db.check_duplicate.assert_awaited_once_with([0.5] * 768, threshold=0.95)


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_extraction_prompt_contains_conversation(
    mock_pro, mock_embed, mock_db
):
    """Extraction prompt sent to Pro contains the conversation text."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    await create_skill.fn(
        conversation="Agent: Hello\nCustomer: I need help with billing"
    )

    prompt = mock_pro.call_args.args[0]
    assert "Agent: Hello" in prompt
    assert "I need help with billing" in prompt


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_metadata_fallback_through_pipeline(
    mock_pro, mock_embed, mock_db
):
    """When Pro omits product_area/issue_type, metadata dict provides fallback."""
    extracted_minimal = {
        "title": "Billing Issue",
        "problem": "Overcharged",
        "resolution": "# Steps\n**Do:** Refund",
        "conditions": [],
        "keywords": ["billing"],
    }
    mock_pro.return_value = extracted_minimal
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    result = await create_skill.fn(
        conversation="conversation",
        metadata={"product_area": "billing", "issue_type": "bug"},
    )

    assert result["created"] is True
    assert result["skill"]["product_area"] == "billing"
    assert result["skill"]["issue_type"] == "bug"


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_conversation_stripped_before_extraction(
    mock_pro, mock_embed, mock_db
):
    """Whitespace-padded conversation is stripped before passing to orchestration."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    await create_skill.fn(conversation="  Agent: Hi  ")

    prompt = mock_pro.call_args.args[0]
    assert "Agent: Hi" in prompt


# --- Response structure ---


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_response_has_all_required_keys(mock_pro, mock_embed, mock_db):
    """Response dict contains all CreateResponse fields."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="conversation")

    for key in ["skill_id", "title", "skill", "created"]:
        assert key in result, f"Missing key: {key}"


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_skill_dict_has_all_model_fields(mock_pro, mock_embed, mock_db):
    """The skill dict in response contains all Skill model fields."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="conversation")

    skill_dict = result["skill"]
    for field in [
        "skill_id",
        "title",
        "version",
        "problem",
        "resolution_md",
        "conditions",
        "keywords",
        "embedding",
        "product_area",
        "issue_type",
        "confidence",
        "times_used",
        "times_confirmed",
        "created_at",
        "updated_at",
    ]:
        assert field in skill_dict, f"Missing field: {field}"


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_new_skill_has_correct_defaults(mock_pro, mock_embed, mock_db):
    """Newly created skill has version=1, confidence=0.5, zero counters."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="conversation")

    assert result["skill"]["confidence"] == 0.5
    assert result["skill"]["version"] == 1
    assert result["skill"]["times_used"] == 0
    assert result["skill"]["times_confirmed"] == 0


# --- Error propagation ---


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_db_error_becomes_tool_error(mock_pro, mock_embed, mock_db):
    """DB error during create_skill → ToolError."""
    from fastmcp.exceptions import ToolError

    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(
        side_effect=RuntimeError("Neo4j write failed")
    )

    from src.server.server import create_skill

    with pytest.raises(ToolError, match="write failed"):
        await create_skill.fn(conversation="conversation")


@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_llm_error_becomes_tool_error(mock_pro, mock_embed):
    """LLM API error during extraction → ToolError."""
    from fastmcp.exceptions import ToolError

    mock_pro.side_effect = RuntimeError("Gemini API error")

    from src.server.server import create_skill

    with pytest.raises(ToolError, match="Gemini API error"):
        await create_skill.fn(conversation="conversation")


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_embed_error_becomes_tool_error(mock_pro, mock_db):
    """Embedding API error → ToolError."""
    from fastmcp.exceptions import ToolError

    mock_pro.return_value = EXTRACTED

    with patch(
        "src.orchestration.create.embed",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Embedding rate limit"),
    ):
        from src.server.server import create_skill

        with pytest.raises(ToolError, match="rate limit"):
            await create_skill.fn(conversation="conversation")


async def test_create_empty_conversation_raises_tool_error():
    """Empty or whitespace conversation → ToolError without calling orchestration."""
    from fastmcp.exceptions import ToolError

    from src.server.server import create_skill

    with pytest.raises(ToolError, match="conversation is required"):
        await create_skill.fn(conversation="")

    with pytest.raises(ToolError, match="conversation is required"):
        await create_skill.fn(conversation="   ")

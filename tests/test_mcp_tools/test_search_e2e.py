"""End-to-end tests for the search_skills MCP tool.

Tests the full pipeline: MCP tool handler → orchestration → mocked LLM + DB.
Only external boundaries (Gemini API, Neo4j) are mocked.
"""
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.skills.models import Skill


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
        confidence=0.8,
        times_used=10,
        times_confirmed=8,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Skill(**defaults)


# --- Happy path: full pipeline ---


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_full_pipeline_returns_match(mock_embed, mock_flash, mock_db):
    """Query → embed → hybrid_search → judge picks → dict with all SkillMatch fields."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = json.dumps({"skill_id": "skill-001"})

    from src.server.server import search_skills

    result = await search_skills.fn(query="can't log in")

    assert result["skill"] is not None
    assert result["skill"]["skill_id"] == "skill-001"
    assert result["skill"]["title"] == "Password Reset"
    assert result["skill"]["resolution_md"] == "# Steps\n**Do:** Reset password"
    assert result["skill"]["confidence"] == 0.8
    assert result["skill"]["conditions"] == ["user is locked out"]
    assert result["query"] == "can't log in"
    assert result["search_time_ms"] > 0


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_full_pipeline_no_candidates(mock_embed, mock_flash, mock_db):
    """No hybrid results → judge not called → null skill."""
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.server.server import search_skills

    result = await search_skills.fn(query="something random")

    assert result["skill"] is None
    assert result["query"] == "something random"
    mock_flash.assert_not_awaited()


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_full_pipeline_judge_rejects(mock_embed, mock_flash, mock_db):
    """Judge returns 'none' → null skill in response."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.5}])
    mock_flash.return_value = json.dumps({"skill_id": "none"})

    from src.server.server import search_skills

    result = await search_skills.fn(query="unrelated question")

    assert result["skill"] is None


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_full_pipeline_judge_unknown_id(mock_embed, mock_flash, mock_db):
    """Judge returns an ID not in candidates → gracefully returns null."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = json.dumps({"skill_id": "unknown-id"})

    from src.server.server import search_skills

    result = await search_skills.fn(query="some query")

    assert result["skill"] is None


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_full_pipeline_multiple_candidates(mock_embed, mock_flash, mock_db):
    """Judge selects correct skill from multiple candidates."""
    skill_a = _make_skill(skill_id="skill-A", title="Billing Refund", confidence=0.6)
    skill_b = _make_skill(skill_id="skill-B", title="Password Reset", confidence=0.9)
    skill_c = _make_skill(skill_id="skill-C", title="Account Deletion", confidence=0.7)
    candidates = [
        {"skill": skill_a, "score": 0.8},
        {"skill": skill_b, "score": 0.85},
        {"skill": skill_c, "score": 0.7},
    ]
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=candidates)
    mock_flash.return_value = json.dumps({"skill_id": "skill-B"})

    from src.server.server import search_skills

    result = await search_skills.fn(query="can't log in")

    assert result["skill"]["skill_id"] == "skill-B"
    assert result["skill"]["title"] == "Password Reset"
    assert result["skill"]["confidence"] == 0.9


# --- Data flow verification ---


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_embeds_with_retrieval_query(mock_embed, mock_flash, mock_db):
    """Embedding uses RETRIEVAL_QUERY task type (asymmetric search)."""
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.server.server import search_skills

    await search_skills.fn(query="test query")

    mock_embed.assert_awaited_once_with("test query", task_type="RETRIEVAL_QUERY")


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_passes_embedding_and_query_to_hybrid_search(
    mock_embed, mock_flash, mock_db
):
    """hybrid_search receives the embedding vector and raw query text."""
    mock_embed.return_value = [0.5] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.server.server import search_skills

    await search_skills.fn(query="password reset help")

    mock_db.hybrid_search.assert_awaited_once_with(
        [0.5] * 768, "password reset help", top_k=5
    )


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_judge_prompt_contains_query_and_candidates(
    mock_embed, mock_flash, mock_db
):
    """Flash judge prompt includes the customer query and formatted candidate data."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = json.dumps({"skill_id": "skill-001"})

    from src.server.server import search_skills

    await search_skills.fn(query="can't log in")

    prompt = mock_flash.call_args.args[0]
    assert "can't log in" in prompt
    assert "skill-001" in prompt
    assert "Password Reset" in prompt
    assert "Customer cannot log in" in prompt
    assert "user is locked out" in prompt


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_strips_query_before_orchestration(mock_embed, mock_flash, mock_db):
    """Whitespace-padded query is stripped before embedding and search."""
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.server.server import search_skills

    await search_skills.fn(query="  test query  ")

    mock_embed.assert_awaited_once_with("test query", task_type="RETRIEVAL_QUERY")


# --- Response structure ---


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_response_dict_has_all_required_keys(
    mock_embed, mock_flash, mock_db
):
    """Response dict matches SearchResponse schema."""
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.server.server import search_skills

    result = await search_skills.fn(query="test")

    assert "skill" in result
    assert "query" in result
    assert "search_time_ms" in result
    assert isinstance(result["search_time_ms"], float)


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_match_dict_has_all_skill_match_keys(
    mock_embed, mock_flash, mock_db
):
    """When a match is found, the skill dict has all SkillMatch fields."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = json.dumps({"skill_id": "skill-001"})

    from src.server.server import search_skills

    result = await search_skills.fn(query="test")
    match = result["skill"]

    for key in ["skill_id", "title", "confidence", "resolution_md", "conditions"]:
        assert key in match, f"Missing SkillMatch key: {key}"


# --- Error propagation ---


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_malformed_json_becomes_tool_error(
    mock_embed, mock_flash, mock_db
):
    """Flash returns invalid JSON → JSONDecodeError → ToolError."""
    from fastmcp.exceptions import ToolError

    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = "not valid json"

    from src.server.server import search_skills

    with pytest.raises(ToolError):
        await search_skills.fn(query="test")


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_db_error_becomes_tool_error(mock_embed, mock_db):
    """DB error during hybrid_search → ToolError."""
    from fastmcp.exceptions import ToolError

    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(
        side_effect=RuntimeError("Neo4j connection lost")
    )

    from src.server.server import search_skills

    with pytest.raises(ToolError, match="Neo4j connection lost"):
        await search_skills.fn(query="test")


@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_embed_error_becomes_tool_error(mock_embed):
    """Embedding API error → ToolError."""
    from fastmcp.exceptions import ToolError

    mock_embed.side_effect = RuntimeError("Gemini API rate limit")

    from src.server.server import search_skills

    with pytest.raises(ToolError, match="rate limit"):
        await search_skills.fn(query="test")


async def test_search_empty_query_raises_tool_error():
    """Empty or whitespace query → ToolError without calling orchestration."""
    from fastmcp.exceptions import ToolError

    from src.server.server import search_skills

    with pytest.raises(ToolError, match="query is required"):
        await search_skills.fn(query="")

    with pytest.raises(ToolError, match="query is required"):
        await search_skills.fn(query="   ")

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.models import SearchResponse


def _make_skill(**overrides):
    from src.skills.models import Skill

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


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash")
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_no_candidates_returns_none(mock_embed, mock_flash, mock_db):
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.orchestration.search import search_skills_orchestration

    result = await search_skills_orchestration("help me log in")

    assert isinstance(result, SearchResponse)
    assert result.skill is None
    assert result.query == "help me log in"
    mock_flash.assert_not_awaited()  # judge shouldn't be called with no candidates


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_judge_picks_skill(mock_embed, mock_flash, mock_db):
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = json.dumps({"skill_id": "skill-001"})

    from src.orchestration.search import search_skills_orchestration

    result = await search_skills_orchestration("can't log in")

    assert result.skill is not None
    assert result.skill.skill_id == "skill-001"
    assert result.skill.title == "Password Reset"
    assert result.skill.resolution_md == "# Steps\n**Do:** Reset password"
    assert result.skill.confidence == 0.8


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_judge_returns_none(mock_embed, mock_flash, mock_db):
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.5}])
    mock_flash.return_value = json.dumps({"skill_id": "none"})

    from src.orchestration.search import search_skills_orchestration

    result = await search_skills_orchestration("unrelated question")

    assert result.skill is None


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_judge_returns_unknown_id(mock_embed, mock_flash, mock_db):
    """Judge returns an ID not in candidates — should gracefully return None."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = json.dumps({"skill_id": "nonexistent-id"})

    from src.orchestration.search import search_skills_orchestration

    result = await search_skills_orchestration("some query")

    assert result.skill is None


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_multiple_candidates_judge_picks_correct_one(
    mock_embed, mock_flash, mock_db
):
    """Judge selects one skill from multiple candidates."""
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

    from src.orchestration.search import search_skills_orchestration

    result = await search_skills_orchestration("can't log in")

    assert result.skill is not None
    assert result.skill.skill_id == "skill-B"
    assert result.skill.title == "Password Reset"
    assert result.skill.confidence == 0.9


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_malformed_judge_json_raises(mock_embed, mock_flash, mock_db):
    """Flash returns garbage — should raise (server.py converts to ToolError)."""
    skill = _make_skill()
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[{"skill": skill, "score": 0.9}])
    mock_flash.return_value = "not valid json at all"

    from src.orchestration.search import search_skills_orchestration

    with pytest.raises(json.JSONDecodeError):
        await search_skills_orchestration("some query")


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_always_returns_positive_search_time(mock_embed, mock_flash, mock_db):
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.orchestration.search import search_skills_orchestration

    result = await search_skills_orchestration("anything")
    assert result.search_time_ms > 0


@patch("src.orchestration.search.db")
@patch("src.orchestration.search.call_flash", new_callable=AsyncMock)
@patch("src.orchestration.search.embed", new_callable=AsyncMock)
async def test_search_uses_retrieval_query_task_type(mock_embed, mock_flash, mock_db):
    """Embed is called with RETRIEVAL_QUERY, not RETRIEVAL_DOCUMENT."""
    mock_embed.return_value = [0.1] * 768
    mock_db.hybrid_search = AsyncMock(return_value=[])

    from src.orchestration.search import search_skills_orchestration

    await search_skills_orchestration("test query")

    mock_embed.assert_awaited_once_with("test query", task_type="RETRIEVAL_QUERY")


def test_format_candidates():
    from src.orchestration.search import _format_candidates

    skill = _make_skill()
    formatted = _format_candidates([{"skill": skill, "score": 0.9}])

    assert "skill-001" in formatted
    assert "Password Reset" in formatted
    assert "0.8" in formatted  # confidence

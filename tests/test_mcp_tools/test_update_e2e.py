"""End-to-end tests for the update_skill MCP tool.

Tests the full pipeline: MCP tool handler → orchestration → mocked LLM + DB.
Only external boundaries (Gemini API, Neo4j) are mocked.
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.skills.models import Skill


REFINED = {
    "title": "Password Reset v2",
    "problem": "Customer cannot log in or is locked out",
    "resolution": "# Steps\n**Do:** Check lockout status first",
    "conditions": ["user is locked out", "user forgot password"],
    "keywords": ["password", "login", "lockout"],
    "product_area": "auth",
    "issue_type": "how-to",
    "changes": ["Added lockout check as first step", "Expanded conditions"],
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
        confidence=0.8,
        times_used=10,
        times_confirmed=8,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Skill(**defaults)


# --- Happy path: full pipeline ---


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_full_pipeline_success(mock_pro, mock_embed, mock_db):
    """skill_id → get_skill → Pro refines → embed → update → response dict."""
    original = _make_skill()
    updated = _make_skill(title="Password Reset v2", version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    result = await update_skill.fn(
        skill_id="skill-001", conversation="new conversation"
    )

    assert result["skill_id"] == "skill-001"
    assert result["title"] == "Password Reset v2"
    assert result["version"] == 2
    assert "Added lockout check as first step" in result["changes"]
    assert "Expanded conditions" in result["changes"]


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_full_pipeline_with_feedback(mock_pro, mock_embed, mock_db):
    """Feedback string flows through to the refinement prompt."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    result = await update_skill.fn(
        skill_id="skill-001",
        conversation="new conversation",
        feedback="The lockout check was helpful",
    )

    prompt = mock_pro.call_args.args[0]
    assert "The lockout check was helpful" in prompt
    assert result["version"] == 2


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_empty_feedback_works(mock_pro, mock_embed, mock_db):
    """Empty feedback string doesn't cause errors."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    result = await update_skill.fn(
        skill_id="skill-001", conversation="conversation"
    )

    assert result["version"] == 2


# --- Data flow verification ---


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_refinement_prompt_includes_existing_data(
    mock_pro, mock_embed, mock_db
):
    """Refinement prompt includes existing skill's title, problem, resolution, and new conversation."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    await update_skill.fn(
        skill_id="skill-001",
        conversation="Agent deviated from playbook",
        feedback="worked better this way",
    )

    prompt = mock_pro.call_args.args[0]
    assert "Password Reset" in prompt  # existing title
    assert "Customer cannot log in" in prompt  # existing problem
    assert "Reset password" in prompt  # existing resolution
    assert "user is locked out" in prompt  # existing conditions
    assert "Agent deviated from playbook" in prompt  # new conversation
    assert "worked better this way" in prompt  # feedback


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_recomputes_embedding_from_refined_fields(
    mock_pro, mock_embed, mock_db
):
    """Embed text uses refined (not original) problem, conditions, keywords."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    await update_skill.fn(skill_id="skill-001", conversation="conversation")

    embed_text = mock_embed.call_args.args[0]
    # Refined fields (not originals)
    assert "cannot log in or is locked out" in embed_text  # refined problem
    assert "forgot password" in embed_text  # new condition from refinement
    assert "lockout" in embed_text  # new keyword from refinement


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_resolution_key_maps_to_resolution_md(
    mock_pro, mock_embed, mock_db
):
    """Pro returns 'resolution' key → SkillUpdate uses 'resolution_md' field."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED  # has "resolution" key
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    await update_skill.fn(skill_id="skill-001", conversation="conversation")

    call_args = mock_db.update_skill.call_args
    skill_update = call_args.args[1]
    assert skill_update.resolution_md == "# Steps\n**Do:** Check lockout status first"


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_skill_update_has_all_refined_fields(
    mock_pro, mock_embed, mock_db
):
    """SkillUpdate passed to DB contains all refined fields + new embedding."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    await update_skill.fn(skill_id="skill-001", conversation="conversation")

    call_args = mock_db.update_skill.call_args
    skill_update = call_args.args[1]
    assert skill_update.title == "Password Reset v2"
    assert skill_update.problem == "Customer cannot log in or is locked out"
    assert skill_update.conditions == ["user is locked out", "user forgot password"]
    assert skill_update.keywords == ["password", "login", "lockout"]
    assert skill_update.embedding == [0.2] * 768
    assert skill_update.product_area == "auth"
    assert skill_update.issue_type == "how-to"


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_db_called_with_correct_skill_id(mock_pro, mock_embed, mock_db):
    """db.update_skill receives the correct skill_id and SkillUpdate."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    await update_skill.fn(skill_id="skill-001", conversation="conversation")

    call_args = mock_db.update_skill.call_args
    assert call_args.args[0] == "skill-001"


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_strips_inputs_before_orchestration(
    mock_pro, mock_embed, mock_db
):
    """Whitespace-padded skill_id and conversation are stripped."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    await update_skill.fn(
        skill_id="  skill-001  ", conversation="  new conversation  "
    )

    # get_skill called with stripped skill_id
    mock_db.get_skill.assert_awaited_once_with("skill-001")
    # Prompt should contain stripped conversation
    prompt = mock_pro.call_args.args[0]
    assert "new conversation" in prompt


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_pro_missing_changes_returns_empty_list(
    mock_pro, mock_embed, mock_db
):
    """When Pro omits 'changes' key, response has empty changes list."""
    refined_no_changes = {
        "title": "Password Reset v2",
        "problem": "updated problem",
        "resolution": "# Steps\n**Do:** Updated steps",
        "conditions": [],
        "keywords": ["password"],
        "product_area": "auth",
        "issue_type": "how-to",
        # "changes" key intentionally omitted
    }
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = refined_no_changes
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    result = await update_skill.fn(
        skill_id="skill-001", conversation="conversation"
    )

    assert result["changes"] == []


# --- Response structure ---


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_response_has_all_required_keys(mock_pro, mock_embed, mock_db):
    """Response dict contains all UpdateResponse fields."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.server.server import update_skill

    result = await update_skill.fn(
        skill_id="skill-001", conversation="conversation"
    )

    for key in ["skill_id", "title", "changes", "version"]:
        assert key in result, f"Missing key: {key}"
    assert isinstance(result["changes"], list)
    assert isinstance(result["version"], int)


# --- Error propagation ---


@patch("src.orchestration.update.db")
async def test_update_skill_not_found_becomes_tool_error(mock_db):
    """get_skill returns None → ValueError → ToolError."""
    from fastmcp.exceptions import ToolError

    mock_db.get_skill = AsyncMock(return_value=None)

    from src.server.server import update_skill

    with pytest.raises(ToolError, match="not found"):
        await update_skill.fn(
            skill_id="nonexistent", conversation="conversation"
        )


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_db_error_becomes_tool_error(mock_pro, mock_embed, mock_db):
    """DB error during update_skill → ToolError."""
    from fastmcp.exceptions import ToolError

    original = _make_skill()
    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(
        side_effect=RuntimeError("Neo4j write failed")
    )

    from src.server.server import update_skill

    with pytest.raises(ToolError, match="write failed"):
        await update_skill.fn(
            skill_id="skill-001", conversation="conversation"
        )


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_llm_error_becomes_tool_error(mock_pro, mock_embed, mock_db):
    """LLM API error during refinement → ToolError."""
    from fastmcp.exceptions import ToolError

    original = _make_skill()
    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.side_effect = RuntimeError("Gemini API error")

    from src.server.server import update_skill

    with pytest.raises(ToolError, match="Gemini API error"):
        await update_skill.fn(
            skill_id="skill-001", conversation="conversation"
        )


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_embed_error_becomes_tool_error(mock_pro, mock_db):
    """Embedding error after refinement → ToolError."""
    from fastmcp.exceptions import ToolError

    original = _make_skill()
    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED

    with patch(
        "src.orchestration.update.embed",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Embedding failed"),
    ):
        from src.server.server import update_skill

        with pytest.raises(ToolError, match="Embedding failed"):
            await update_skill.fn(
                skill_id="skill-001", conversation="conversation"
            )


async def test_update_empty_skill_id_raises_tool_error():
    """Empty skill_id → ToolError."""
    from fastmcp.exceptions import ToolError

    from src.server.server import update_skill

    with pytest.raises(ToolError, match="skill_id is required"):
        await update_skill.fn(skill_id="", conversation="conversation")

    with pytest.raises(ToolError, match="skill_id is required"):
        await update_skill.fn(skill_id="   ", conversation="conversation")


async def test_update_empty_conversation_raises_tool_error():
    """Empty conversation → ToolError."""
    from fastmcp.exceptions import ToolError

    from src.server.server import update_skill

    with pytest.raises(ToolError, match="conversation is required"):
        await update_skill.fn(skill_id="skill-001", conversation="")

    with pytest.raises(ToolError, match="conversation is required"):
        await update_skill.fn(skill_id="skill-001", conversation="   ")

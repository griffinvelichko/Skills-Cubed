from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.models import UpdateResponse


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


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_skill_success(mock_pro, mock_embed, mock_db):
    original = _make_skill()
    updated = _make_skill(title="Password Reset v2", version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.orchestration.update import update_skill_orchestration

    result = await update_skill_orchestration("skill-001", "new conversation", "worked")

    assert isinstance(result, UpdateResponse)
    assert result.skill_id == "skill-001"
    assert result.version == 2
    assert "Added lockout check as first step" in result.changes
    mock_db.update_skill.assert_awaited_once()


@patch("src.orchestration.update.db")
async def test_update_skill_not_found_raises(mock_db):
    mock_db.get_skill = AsyncMock(return_value=None)

    from src.orchestration.update import update_skill_orchestration

    with pytest.raises(ValueError, match="not found"):
        await update_skill_orchestration("bad-id", "conversation", "")


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_recomputes_embedding(mock_pro, mock_embed, mock_db):
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.orchestration.update import update_skill_orchestration

    await update_skill_orchestration("skill-001", "conversation", "feedback")

    # Verify embedding was recomputed from refined fields
    embed_text = mock_embed.call_args.args[0]
    assert "locked out" in embed_text
    assert "lockout" in embed_text


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_passes_existing_skill_to_prompt(mock_pro, mock_embed, mock_db):
    """Refinement prompt should include the existing skill's data."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.orchestration.update import update_skill_orchestration

    await update_skill_orchestration("skill-001", "conversation", "feedback")

    prompt_text = mock_pro.call_args.args[0]
    assert "Password Reset" in prompt_text  # existing title
    assert "Customer cannot log in" in prompt_text  # existing problem
    assert "Reset password" in prompt_text  # existing resolution


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_constructs_correct_skill_update(mock_pro, mock_embed, mock_db):
    """SkillUpdate passed to db.update_skill should have all refined fields."""
    original = _make_skill()
    updated = _make_skill(title="Password Reset v2", version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.orchestration.update import update_skill_orchestration

    await update_skill_orchestration("skill-001", "conversation", "")

    call_args = mock_db.update_skill.call_args
    skill_update = call_args.args[1]
    assert skill_update.title == "Password Reset v2"
    assert skill_update.problem == "Customer cannot log in or is locked out"
    assert skill_update.embedding == [0.2] * 768
    assert "lockout" in skill_update.keywords


@patch("src.orchestration.update.db")
@patch("src.orchestration.update.embed", new_callable=AsyncMock)
@patch("src.orchestration.update.call_pro_json", new_callable=AsyncMock)
async def test_update_empty_feedback_still_works(mock_pro, mock_embed, mock_db):
    """Empty feedback string should not cause errors."""
    original = _make_skill()
    updated = _make_skill(version=2)

    mock_db.get_skill = AsyncMock(return_value=original)
    mock_pro.return_value = REFINED
    mock_embed.return_value = [0.2] * 768
    mock_db.update_skill = AsyncMock(return_value=updated)

    from src.orchestration.update import update_skill_orchestration

    result = await update_skill_orchestration("skill-001", "conversation", "")

    assert result.version == 2

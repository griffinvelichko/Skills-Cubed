import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.models import CreateResponse


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
        confidence=0.5,
        times_used=0,
        times_confirmed=0,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(overrides)
    return Skill(**defaults)


EXTRACTED = {
    "title": "Password Reset",
    "problem": "Customer cannot log in",
    "resolution": "# Steps\n**Do:** Reset password",
    "conditions": ["user is locked out"],
    "keywords": ["password", "login"],
    "product_area": "auth",
    "issue_type": "how-to",
}


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_new_skill(mock_pro, mock_embed, mock_db):
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.orchestration.create import create_skill_orchestration

    result = await create_skill_orchestration("Agent: Hi\nCustomer: Can't log in")

    assert isinstance(result, CreateResponse)
    assert result.created is True
    assert result.title == "Password Reset"
    mock_db.create_skill.assert_awaited_once()


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_returns_existing_on_duplicate(mock_pro, mock_embed, mock_db):
    existing = _make_skill()
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=existing)

    from src.orchestration.create import create_skill_orchestration

    result = await create_skill_orchestration("Agent: Hi\nCustomer: Can't log in")

    assert result.created is False
    assert result.skill_id == "skill-001"
    mock_db.create_skill.assert_not_called()


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_embeds_problem_conditions_keywords(mock_pro, mock_embed, mock_db):
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.orchestration.create import create_skill_orchestration

    await create_skill_orchestration("conversation text")

    embed_text = mock_embed.call_args.args[0]
    assert "Customer cannot log in" in embed_text
    assert "user is locked out" in embed_text
    assert "password" in embed_text
    # Resolution should NOT be in the embed text
    assert "**Do:**" not in embed_text


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_new_skill_gets_valid_uuid(mock_pro, mock_embed, mock_db):
    """Created skill should have a valid UUID-format skill_id."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.orchestration.create import create_skill_orchestration

    result = await create_skill_orchestration("Agent: Help\nCustomer: Can't log in")

    assert result.created is True
    # UUID4 format: 8-4-4-4-12 hex chars
    assert len(result.skill_id) == 36
    assert result.skill_id.count("-") == 4


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_metadata_fallback(mock_pro, mock_embed, mock_db):
    """When Pro omits product_area/issue_type, metadata dict provides fallback."""
    extracted_no_area = {
        "title": "Billing Issue",
        "problem": "Overcharged",
        "resolution": "# Steps\n**Do:** Refund",
        "conditions": [],
        "keywords": ["billing"],
    }
    mock_pro.return_value = extracted_no_area
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.orchestration.create import create_skill_orchestration

    result = await create_skill_orchestration(
        "conversation",
        metadata={"product_area": "billing", "issue_type": "bug"},
    )

    assert result.created is True
    assert result.skill["product_area"] == "billing"
    assert result.skill["issue_type"] == "bug"


@patch("src.orchestration.create.db")
@patch("src.orchestration.create.embed", new_callable=AsyncMock)
@patch("src.orchestration.create.call_pro_json", new_callable=AsyncMock)
async def test_create_skill_response_contains_full_skill_dict(mock_pro, mock_embed, mock_db):
    """CreateResponse.skill dict should contain all core skill fields."""
    mock_pro.return_value = EXTRACTED
    mock_embed.return_value = [0.1] * 768
    mock_db.check_duplicate = AsyncMock(return_value=None)
    mock_db.create_skill = AsyncMock(side_effect=lambda s: s)

    from src.orchestration.create import create_skill_orchestration

    result = await create_skill_orchestration("conversation")

    skill_dict = result.skill
    for field in ["skill_id", "title", "problem", "resolution_md", "conditions",
                  "keywords", "embedding", "confidence", "created_at", "updated_at"]:
        assert field in skill_dict, f"Missing field: {field}"

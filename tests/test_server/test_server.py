from unittest.mock import AsyncMock, patch

import pytest

from src.server.models import CreateResponse, SearchResponse, UpdateResponse


# FastMCP's @mcp.tool() wraps functions in FunctionTool objects.
# We test the handler logic by calling the underlying .fn attribute.


@patch("src.server.server.search_skills_orchestration", new_callable=AsyncMock)
async def test_search_skills_calls_orchestration(mock_orch):
    mock_orch.return_value = SearchResponse(
        skill=None, query="test", search_time_ms=5.0
    )

    from src.server.server import search_skills

    result = await search_skills.fn(query="test query")

    assert result["skill"] is None
    assert result["query"] == "test"


@patch("src.server.server.search_skills_orchestration", new_callable=AsyncMock)
async def test_search_skills_empty_query_raises(mock_orch):
    from fastmcp.exceptions import ToolError
    from src.server.server import search_skills

    with pytest.raises(ToolError):
        await search_skills.fn(query="")

    with pytest.raises(ToolError):
        await search_skills.fn(query="   ")


@patch("src.server.server.create_skill_orchestration", new_callable=AsyncMock)
async def test_create_skill_calls_orchestration(mock_orch):
    mock_orch.return_value = CreateResponse(
        skill_id="s-1", title="Test", skill={}, created=True
    )

    from src.server.server import create_skill

    result = await create_skill.fn(conversation="Agent: Hi\nCustomer: Help")

    assert result["created"] is True
    assert result["skill_id"] == "s-1"


@patch("src.server.server.create_skill_orchestration", new_callable=AsyncMock)
async def test_create_skill_empty_conversation_raises(mock_orch):
    from fastmcp.exceptions import ToolError
    from src.server.server import create_skill

    with pytest.raises(ToolError):
        await create_skill.fn(conversation="")


@patch("src.server.server.update_skill_orchestration", new_callable=AsyncMock)
async def test_update_skill_calls_orchestration(mock_orch):
    mock_orch.return_value = UpdateResponse(
        skill_id="s-1", title="Updated", changes=["tweaked step 1"], version=2
    )

    from src.server.server import update_skill

    result = await update_skill.fn(skill_id="s-1", conversation="new conversation")

    assert result["version"] == 2


@patch("src.server.server.update_skill_orchestration", new_callable=AsyncMock)
async def test_update_skill_empty_id_raises(mock_orch):
    from fastmcp.exceptions import ToolError
    from src.server.server import update_skill

    with pytest.raises(ToolError):
        await update_skill.fn(skill_id="", conversation="conversation")


@patch("src.server.server.update_skill_orchestration", new_callable=AsyncMock)
async def test_update_skill_empty_conversation_raises(mock_orch):
    from fastmcp.exceptions import ToolError
    from src.server.server import update_skill

    with pytest.raises(ToolError):
        await update_skill.fn(skill_id="s-1", conversation="")


@patch("src.server.server.search_skills_orchestration", new_callable=AsyncMock)
async def test_search_orchestration_error_becomes_tool_error(mock_orch):
    """Generic exceptions from orchestration are converted to ToolError."""
    from fastmcp.exceptions import ToolError
    from src.server.server import search_skills

    mock_orch.side_effect = RuntimeError("Gemini API error: rate limited")

    with pytest.raises(ToolError, match="rate limited"):
        await search_skills.fn(query="test")


@patch("src.server.server.update_skill_orchestration", new_callable=AsyncMock)
async def test_update_value_error_becomes_tool_error(mock_orch):
    """ValueError (skill not found) from orchestration is converted to ToolError."""
    from fastmcp.exceptions import ToolError
    from src.server.server import update_skill

    mock_orch.side_effect = ValueError("Skill bad-id not found. Use search_skills to find the correct ID.")

    with pytest.raises(ToolError, match="not found"):
        await update_skill.fn(skill_id="bad-id", conversation="conversation")


@patch("src.server.server.create_skill_orchestration", new_callable=AsyncMock)
async def test_create_orchestration_error_becomes_tool_error(mock_orch):
    from fastmcp.exceptions import ToolError
    from src.server.server import create_skill

    mock_orch.side_effect = Exception("LLM extraction failed")

    with pytest.raises(ToolError, match="extraction failed"):
        await create_skill.fn(conversation="some conversation")


@patch("src.server.server.search_skills_orchestration", new_callable=AsyncMock)
async def test_search_strips_whitespace_from_query(mock_orch):
    """Query should be stripped before passing to orchestration."""
    mock_orch.return_value = SearchResponse(
        skill=None, query="test", search_time_ms=1.0
    )

    from src.server.server import search_skills

    await search_skills.fn(query="  test query  ")

    mock_orch.assert_awaited_once_with("test query")

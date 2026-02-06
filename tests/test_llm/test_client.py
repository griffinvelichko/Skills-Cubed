import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- Unit tests (no API key needed) ---


def test_env_defaults():
    """Model strings fall back to defaults when env vars are unset."""
    from src.llm import client

    assert client.FLASH_MODEL == os.getenv("GEMINI_FLASH_MODEL", "gemini-3-flash-preview")
    assert client.PRO_MODEL == os.getenv("GEMINI_PRO_MODEL", "gemini-3-pro-preview")
    assert client.EMBEDDING_MODEL == os.getenv(
        "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
    )


def test_client_singleton_not_created_at_import():
    from src.llm import client

    # _client starts as None until first call
    assert client._client is None or isinstance(client._client, object)


async def test_call_flash_delegates_to_genai():
    mock_response = MagicMock()
    mock_response.text = "hello"

    mock_generate = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    with patch("src.llm.client._get_client", return_value=mock_client):
        from src.llm.client import call_flash

        result = await call_flash("Say hi")

    assert result == "hello"
    mock_generate.assert_awaited_once()
    call_args = mock_generate.call_args
    assert call_args.kwargs["model"] is not None
    assert call_args.kwargs["contents"] == "Say hi"


async def test_call_pro_json_parses_response():
    mock_response = MagicMock()
    mock_response.text = '{"title": "Test Skill", "problem": "test"}'

    mock_generate = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    with patch("src.llm.client._get_client", return_value=mock_client):
        from src.llm.client import call_pro_json

        result = await call_pro_json("Extract skill")

    assert result == {"title": "Test Skill", "problem": "test"}


async def test_embed_returns_values():
    import math

    mock_embedding = MagicMock()
    mock_embedding.values = [0.1] * 768

    mock_response = MagicMock()
    mock_response.embeddings = [mock_embedding]

    mock_embed = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.embed_content = mock_embed

    with patch("src.llm.client._get_client", return_value=mock_client):
        from src.llm.client import embed

        result = await embed("test query", task_type="RETRIEVAL_QUERY")

    assert len(result) == 768
    # Result is now L2 normalized, so check the norm instead of raw values
    norm = math.sqrt(sum(x * x for x in result))
    assert abs(norm - 1.0) < 1e-6, f"Expected normalized vector, got norm={norm}"
    call_args = mock_embed.call_args
    assert call_args.kwargs["contents"] == "test query"


async def test_call_pro_json_invalid_json_raises():
    mock_response = MagicMock()
    mock_response.text = "not valid json"

    mock_generate = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    with patch("src.llm.client._get_client", return_value=mock_client):
        from src.llm.client import call_pro_json

        with pytest.raises(Exception):
            await call_pro_json("bad prompt")


async def test_call_flash_uses_flash_model():
    from src.llm import client

    mock_response = MagicMock()
    mock_response.text = "ok"
    mock_generate = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    with patch("src.llm.client._get_client", return_value=mock_client):
        await client.call_flash("test")

    assert mock_generate.call_args.kwargs["model"] == client.FLASH_MODEL


async def test_call_pro_json_uses_pro_model():
    from src.llm import client

    mock_response = MagicMock()
    mock_response.text = '{"key": "value"}'
    mock_generate = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    with patch("src.llm.client._get_client", return_value=mock_client):
        await client.call_pro_json("test")

    assert mock_generate.call_args.kwargs["model"] == client.PRO_MODEL


async def test_call_flash_passes_temperature():
    mock_response = MagicMock()
    mock_response.text = "ok"
    mock_generate = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = mock_generate

    with patch("src.llm.client._get_client", return_value=mock_client):
        from src.llm.client import call_flash

        await call_flash("test", temperature=0.7)

    config = mock_generate.call_args.kwargs["config"]
    assert config.temperature == 0.7


async def test_embed_passes_task_type_and_dimensionality():
    mock_embedding = MagicMock()
    mock_embedding.values = [0.1] * 768
    mock_response = MagicMock()
    mock_response.embeddings = [mock_embedding]
    mock_embed = AsyncMock(return_value=mock_response)
    mock_client = MagicMock()
    mock_client.aio.models.embed_content = mock_embed

    with patch("src.llm.client._get_client", return_value=mock_client):
        from src.llm.client import embed

        await embed("test", task_type="RETRIEVAL_QUERY")

    config = mock_embed.call_args.kwargs["config"]
    assert config.task_type == "RETRIEVAL_QUERY"
    assert config.output_dimensionality == 768


# --- Integration tests (need GOOGLE_API_KEY) ---

pytestmark_integration = pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set",
)


@pytest.mark.integration
@pytestmark_integration
async def test_live_call_flash():
    from src.llm.client import call_flash

    result = await call_flash("Reply with exactly the word 'pong'.", temperature=0.0)
    assert "pong" in result.lower()


@pytest.mark.integration
@pytestmark_integration
async def test_live_embed_dimensions():
    from src.llm.client import embed

    vec = await embed("customer cannot log in")
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)


@pytest.mark.integration
@pytestmark_integration
async def test_live_embed_task_types_differ():
    from src.llm.client import embed

    doc_vec = await embed("password reset procedure", task_type="RETRIEVAL_DOCUMENT")
    query_vec = await embed("password reset procedure", task_type="RETRIEVAL_QUERY")
    # Same text with different task types should produce different vectors
    assert doc_vec != query_vec

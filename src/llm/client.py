import json
import math
import os

from google import genai

_client = None

FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-3-flash-preview")
PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-3-pro-preview")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _client


async def call_flash(prompt: str, temperature: float = 0.2) -> str:
    client = _get_client()
    response = await client.aio.models.generate_content(
        model=FLASH_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(temperature=temperature),
    )
    return response.text


async def call_pro_json(prompt: str, temperature: float = 0.3) -> dict:
    client = _get_client()
    response = await client.aio.models.generate_content(
        model=PRO_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
        ),
    )
    return json.loads(response.text)


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2 normalize vector. Required for gemini-embedding-001 at <3072 dimensions."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


async def embed(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    client = _get_client()
    response = await client.aio.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=genai.types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=768,
        ),
    )
    raw = response.embeddings[0].values
    # gemini-embedding-001 only pre-normalizes at 3072 dims
    # At 768 or 1536 dims, we must normalize manually
    return _l2_normalize(raw)

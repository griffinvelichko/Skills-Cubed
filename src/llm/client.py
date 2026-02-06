import json
import os

from google import genai

_client = None

FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.0-flash")
PRO_MODEL = os.getenv("GEMINI_PRO_MODEL", "gemini-2.0-pro")
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
    return response.embeddings[0].values

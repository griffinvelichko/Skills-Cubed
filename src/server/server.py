import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from src.db import ensure_indexes
from src.orchestration.search import search_skills_orchestration
from src.orchestration.create import create_skill_orchestration
from src.orchestration.update import update_skill_orchestration

# Load .env for local development (Render sets env vars via dashboard)
load_dotenv()


@asynccontextmanager
async def lifespan(server):
    await ensure_indexes()
    yield


mcp = FastMCP(
    "skills-cubed",
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)


@mcp.tool()
async def search_skills(query: str) -> dict:
    """Query existing resolution patterns via hybrid search."""
    if not query or not query.strip():
        raise ToolError("query is required")
    try:
        response = await search_skills_orchestration(query.strip())
        return response.model_dump()
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool()
async def create_skill(
    conversation: str,
    resolution_confirmed: bool = False,
    metadata: dict | None = None,
) -> dict:
    """Extract a new skill document from a successful resolution."""
    if not conversation or not conversation.strip():
        raise ToolError("conversation is required")
    try:
        response = await create_skill_orchestration(
            conversation.strip(), resolution_confirmed, metadata or {}
        )
        return response.model_dump()
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool()
async def update_skill(
    skill_id: str,
    conversation: str,
    feedback: str = "",
) -> dict:
    """Refine an existing skill with new conversation data."""
    if not skill_id or not skill_id.strip():
        raise ToolError("skill_id is required")
    if not conversation or not conversation.strip():
        raise ToolError("conversation is required")
    try:
        response = await update_skill_orchestration(
            skill_id.strip(), conversation.strip(), feedback
        )
        return response.model_dump()
    except ValueError as e:
        raise ToolError(str(e)) from e
    except Exception as e:
        raise ToolError(str(e)) from e


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="http", host="0.0.0.0", port=port)

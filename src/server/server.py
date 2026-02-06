import os

from fastmcp import FastMCP

mcp = FastMCP("skills-cubed")


@mcp.tool()
def search_skills(query: str) -> list[dict]:
    """Query existing resolution patterns via hybrid search."""
    return [
        {
            "skill_id": "SKL-001",
            "title": "Password Reset Flow",
            "confidence": 0.92,
            "resolution_summary": "Guide user through Settings > Security > Reset Password. If locked out, verify identity via backup email.",
        }
    ]


@mcp.tool()
def create_skill(conversation_id: str, resolution_summary: str) -> dict:
    """Extract a new skill document from a successful resolution."""
    return {
        "skill_id": "SKL-002",
        "status": "created",
        "conversation_id": conversation_id,
        "resolution_summary": resolution_summary,
    }


@mcp.tool()
def update_skill(skill_id: str, conversation_id: str, refinement: str) -> dict:
    """Refine an existing skill with new conversation data."""
    return {
        "skill_id": skill_id,
        "status": "updated",
        "conversation_id": conversation_id,
        "refinement": refinement,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="http", host="0.0.0.0", port=port)

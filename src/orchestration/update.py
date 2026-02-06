from src.db import queries as db
from src.llm.client import call_pro_json, embed
from src.llm.prompts import REFINEMENT_PROMPT
from src.server.models import UpdateResponse
from src.skills.models import SkillUpdate


async def update_skill_orchestration(
    skill_id: str,
    conversation: str,
    feedback: str = "",
) -> UpdateResponse:
    skill = await db.get_skill(skill_id)
    if skill is None:
        raise ValueError(
            f"Skill {skill_id} not found. Use search_skills to find the correct ID."
        )

    prompt = REFINEMENT_PROMPT.format(
        title=skill.title,
        problem=skill.problem,
        resolution=skill.resolution_md,
        conditions=skill.conditions,
        keywords=skill.keywords,
        conversation=conversation,
        feedback=feedback,
    )
    refined = await call_pro_json(prompt)

    embed_text = " ".join([
        refined["problem"],
        " ".join(refined.get("conditions", [])),
        " ".join(refined.get("keywords", [])),
    ])
    new_embedding = await embed(embed_text)

    updates = SkillUpdate(
        title=refined.get("title"),
        problem=refined.get("problem"),
        resolution_md=refined.get("resolution"),
        conditions=refined.get("conditions"),
        keywords=refined.get("keywords"),
        embedding=new_embedding,
        product_area=refined.get("product_area"),
        issue_type=refined.get("issue_type"),
    )

    updated = await db.update_skill(skill_id, updates)

    return UpdateResponse(
        skill_id=updated.skill_id,
        title=updated.title,
        changes=refined.get("changes", []),
        version=updated.version,
    )

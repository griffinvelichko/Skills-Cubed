from src.db import queries as db
from src.llm.client import call_pro_json, embed
from src.llm.prompts import EXTRACTION_PROMPT
from src.server.models import CreateResponse
from src.skills.models import Skill


async def create_skill_orchestration(
    conversation: str,
    resolution_confirmed: bool = False,
    metadata: dict | None = None,
) -> CreateResponse:
    metadata = metadata or {}

    prompt = EXTRACTION_PROMPT.format(conversation=conversation)
    extracted = await call_pro_json(prompt)

    embed_text = " ".join([
        extracted["problem"],
        " ".join(extracted.get("conditions", [])),
        " ".join(extracted.get("keywords", [])),
    ])
    embedding = await embed(embed_text)

    duplicate = await db.check_duplicate(embedding, threshold=0.95)
    if duplicate is not None:
        return CreateResponse(
            skill_id=duplicate.skill_id,
            title=duplicate.title,
            skill=duplicate.model_dump(),
            created=False,
        )

    skill = Skill.create_new(
        title=extracted["title"],
        problem=extracted["problem"],
        resolution_md=extracted["resolution"],
        embedding=embedding,
        conditions=extracted.get("conditions", []),
        keywords=extracted.get("keywords", []),
        product_area=extracted.get("product_area", metadata.get("product_area", "")),
        issue_type=extracted.get("issue_type", metadata.get("issue_type", "")),
    )

    created = await db.create_skill(skill)

    return CreateResponse(
        skill_id=created.skill_id,
        title=created.title,
        skill=created.model_dump(),
        created=True,
    )

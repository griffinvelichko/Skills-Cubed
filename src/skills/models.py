import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from src.utils.config import EMBEDDING_DIM, validate_embedding


class Skill(BaseModel):
    # Identity
    skill_id: str
    title: str
    version: int = 1

    # Content
    problem: str
    resolution: str
    conditions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    # Embeddings
    embedding: list[float]

    # Metadata
    product_area: str = ""
    issue_type: str = ""
    confidence: float = 0.5
    times_used: int = 0
    times_confirmed: int = 0

    # Timestamps
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "Skill":
        if not self.embedding:
            raise ValueError("embedding must not be empty")
        if len(self.embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"Expected embedding dim {EMBEDDING_DIM}, got {len(self.embedding)}"
            )
        if not self.created_at:
            raise ValueError("created_at must not be empty")
        if not self.updated_at:
            raise ValueError("updated_at must not be empty")
        return self

    @staticmethod
    def create_new(
        title: str,
        problem: str,
        resolution: str,
        embedding: list[float],
        conditions: list[str] | None = None,
        keywords: list[str] | None = None,
        product_area: str = "",
        issue_type: str = "",
    ) -> "Skill":
        now = datetime.now(timezone.utc).isoformat()
        return Skill(
            skill_id=str(uuid.uuid4()),
            title=title,
            problem=problem,
            resolution=resolution,
            embedding=embedding,
            conditions=conditions or [],
            keywords=keywords or [],
            product_area=product_area,
            issue_type=issue_type,
            created_at=now,
            updated_at=now,
        )

    def to_neo4j_props(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_neo4j_node(cls, node: dict) -> "Skill":
        return cls(**node)


class SkillUpdate(BaseModel):
    title: str | None = None
    problem: str | None = None
    resolution: str | None = None
    conditions: list[str] | None = None
    keywords: list[str] | None = None
    embedding: list[float] | None = None
    product_area: str | None = None
    issue_type: str | None = None
    confidence: float | None = None

from pydantic import BaseModel, Field


# --- Search Skills ---

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.0


class SkillMatch(BaseModel):
    skill_id: str          # UUID (application-generated)
    title: str
    score: float           # Relevance score [0, 1], hybrid of keyword + vector
    resolution: str
    conditions: list[str]


class SearchResponse(BaseModel):
    matches: list[SkillMatch]
    query: str
    search_time_ms: float


# --- Create Skill ---

class CreateRequest(BaseModel):
    conversation: str
    resolution_confirmed: bool = False
    metadata: dict = Field(default_factory=dict)


class CreateResponse(BaseModel):
    skill_id: str          # UUID (application-generated)
    title: str
    skill: dict
    created: bool


# --- Update Skill ---

class UpdateRequest(BaseModel):
    skill_id: str
    conversation: str
    feedback: str = ""


class UpdateResponse(BaseModel):
    skill_id: str
    title: str
    changes: list[str]
    version: int


# --- Errors ---

class ErrorResponse(BaseModel):
    error: str
    detail: str

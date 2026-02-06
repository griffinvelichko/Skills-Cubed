from pydantic import BaseModel, Field


# --- Search Skills ---

class SearchRequest(BaseModel):
    query: str


class SkillMatch(BaseModel):
    skill_id: str          # UUID (application-generated)
    title: str
    confidence: float      # Historical success rate [0, 1]
    resolution_md: str     # Full .md playbook (Do/Check/Say steps)
    conditions: list[str]


class SearchResponse(BaseModel):
    skill: SkillMatch | None  # Best match, or None if no playbook fits
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

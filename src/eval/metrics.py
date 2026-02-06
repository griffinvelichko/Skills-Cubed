import json
import time
from dataclasses import dataclass, asdict


@dataclass
class ConversationMetrics:
    conversation_id: str
    judge_score: float  # 1-5 from LLM judge
    skill_used: bool
    skill_id: str | None = None
    resolution_time_ms: float = 0.0


@dataclass
class AggregateMetrics:
    total_conversations: int = 0
    avg_judge_score: float = 0.0
    skill_use_rate: float = 0.0
    avg_resolution_time_ms: float = 0.0

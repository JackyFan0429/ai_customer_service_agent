"""Domain models shared by the agent pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Route(StrEnum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


class Intent(StrEnum):
    GREETING_IDENTITY = "greeting_identity"
    SUPPORT_QUESTION = "support_question"
    ACCOUNT_SPECIFIC = "account_specific"
    LIVE_STATUS = "live_status"
    OUT_OF_SCOPE = "out_of_scope"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class QueryUnderstanding:
    intent: Intent
    normalized_query: str
    needs_knowledge_base: bool
    clarification_question: str
    confidence: float


@dataclass(frozen=True)
class Evidence:
    document_id: str
    title: str
    text: str
    precedence: str
    authority: str
    audience: str | None
    source_url: str | None
    score: float
    current: bool
    generation_policy: str
    conflict_status: str

    @classmethod
    def from_record(cls, record: dict[str, Any], *, current: bool) -> "Evidence":
        return cls(
            document_id=str(record["document_id"]),
            title=str(record.get("title", "")),
            text=str(record.get("text", "")),
            precedence=str(record.get("precedence", "P3")),
            authority=str(record.get("authority", "unknown")),
            audience=record.get("audience"),
            source_url=record.get("source_url"),
            score=float(record.get("score", 0.0)),
            current=current,
            generation_policy=str(record.get("generation_policy", "")),
            conflict_status=str(record.get("conflict_status", "unknown")),
        )


@dataclass(frozen=True)
class PolicyDecision:
    route: Route
    reason: str
    customer_message: str | None = None
    internal_document_ids: tuple[str, ...] = ()


@dataclass
class AgentResponse:
    answer: str
    route: Route
    reason: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None
    provider: str = "local"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["route"] = self.route.value
        return data

"""End-to-end orchestration for retrieval, policy, and generation."""

from __future__ import annotations

from datetime import date

from .config import AgentConfig
from .models import AgentResponse, Evidence, Route
from .policy import decide_route, select_evidence
from .providers import LocalProvider, OpenAIProvider, Provider
from .retrieval import HybridRetriever
from .session import SessionStore


def _citations(evidence: list[Evidence]) -> list[dict[str, object]]:
    return [
        {
            "document_id": item.document_id,
            "title": item.title,
            "precedence": item.precedence,
            "authority": item.authority,
            "source_url": (
                item.source_url
                if item.source_url and item.source_url.startswith(("https://", "http://"))
                else None
            ),
            "score": round(item.score, 6),
        }
        for item in evidence
    ]


class CustomerAgent:
    def __init__(
        self,
        config: AgentConfig,
        *,
        provider: Provider | None = None,
        retriever: HybridRetriever | None = None,
        sessions: SessionStore | None = None,
        today: date | None = None,
    ):
        config.validate()
        self.config = config
        self.retriever = retriever or HybridRetriever(config.corpus_path)
        self.sessions = sessions or SessionStore()
        self.today = today or date.today()
        self.provider = provider or self._make_provider()

    def _make_provider(self) -> Provider:
        if self.config.provider == "local":
            return LocalProvider()
        return OpenAIProvider(
            api_key=self.config.api_key or "",
            model=self.config.model or "",
            api_base=self.config.api_base,
            timeout_seconds=self.config.timeout_seconds,
        )

    def respond(self, query: str, *, session_id: str | None = None) -> AgentResponse:
        query = query.strip()
        if not query:
            raise ValueError("query 不能为空")
        contextual_query = self.sessions.contextualize(session_id, query)
        records = self.retriever.search(contextual_query, top_k=self.config.top_k)
        customer, internal = select_evidence(
            records,
            today=self.today,
            min_score=self.config.min_score,
            query=contextual_query,
        )
        decision = decide_route(query, customer, internal)
        if decision.route is Route.ANSWER and decision.customer_message:
            answer = decision.customer_message
            citations = []
        elif decision.route is Route.ANSWER:
            answer = self.provider.generate(query, customer, self.config.max_evidence_chars)
            # The local renderer quotes only its leading evidence item. Model
            # providers receive the complete curated set, so expose that set
            # for audit without asking the model to invent citations.
            cited_evidence = customer[:1] if self.provider.name == "local" else customer
            citations = _citations(cited_evidence)
        else:
            answer = decision.customer_message or "请补充更多信息。"
            citations = []

        if session_id:
            self.sessions.add(session_id, "user", query)
            self.sessions.add(session_id, "assistant", answer)
        return AgentResponse(
            answer=answer,
            route=decision.route,
            reason=decision.reason,
            citations=citations,
            session_id=session_id,
            provider=self.provider.name,
        )

"""End-to-end orchestration for retrieval, policy, and generation."""

from __future__ import annotations

from datetime import date

from .config import AgentConfig
from .models import AgentResponse, Evidence, Intent, QueryUnderstanding, Route
from .policy import decide_route, select_evidence
from .prompts import budget_evidence
from .providers import LocalProvider, ResponsesProvider, Provider
from .retrieval import HybridRetriever, critical_query_terms
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
        self.today = today
        self.provider = provider or self._make_provider()

    def _make_provider(self) -> Provider:
        if self.config.provider == "local":
            return LocalProvider()
        return ResponsesProvider(
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
        understanding = self.provider.understand(query, contextual_query)
        # A model rewrite must not discard explicit identifiers. Fail closed
        # instead of answering against a different error or product version.
        if not critical_query_terms(query).issubset(critical_query_terms(understanding.normalized_query)):
            understanding = QueryUnderstanding(
                Intent.UNCLEAR, query, False,
                "请确认当前产品、完整错误码与已经尝试的步骤，我需要保留这些信息才能继续排查。", 0.0,
            )
        retrieval_query = understanding.normalized_query
        records = (
            self.retriever.search(retrieval_query, top_k=self.config.top_k)
            if understanding.needs_knowledge_base
            else []
        )
        customer, internal = select_evidence(
            records,
            today=self.today or date.today(),
            min_score=self.config.min_score,
            query=retrieval_query,
        )
        customer = budget_evidence(customer, self.config.max_evidence_chars)
        decision = decide_route(query, customer, internal, understanding)
        if decision.route is Route.ANSWER and decision.customer_message:
            answer = decision.customer_message
            citations = []
        elif decision.route is Route.ANSWER:
            answer = self.provider.generate(retrieval_query, customer, self.config.max_evidence_chars)
            # The local renderer quotes only its leading evidence item. Model
            # providers receive the complete curated set, so expose that set
            # for audit without asking the model to invent citations.
            cited_evidence = (
                ([item for item in customer if item.precedence == "P1"] or customer)[:1]
                if self.provider.name == "local" else customer
            )
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

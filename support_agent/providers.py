"""Text generation providers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .models import Evidence, Intent, QueryUnderstanding
from .prompts import INTENT_INSTRUCTIONS, SYSTEM_INSTRUCTIONS, build_model_input


class GenerationError(RuntimeError):
    """Raised when a generation provider cannot produce a response."""


class Provider(Protocol):
    name: str

    def understand(self, query: str, context: str) -> QueryUnderstanding: ...

    def generate(self, query: str, evidence: list[Evidence], max_chars: int) -> str: ...


@dataclass
class LocalProvider:
    """Deterministic offline renderer for testing and safe fallback."""

    name: str = "local"

    def understand(self, query: str, context: str) -> QueryUnderstanding:
        normalized = query.strip()
        try:
            state = json.loads(context)
        except (ValueError, TypeError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        normalized = str(state.get("resolved_question", normalized))
        folded = normalized.casefold()
        if state.get("unresolved_attempt"):
            return QueryUnderstanding(
                intent=Intent.UNCLEAR, normalized_query=normalized,
                needs_knowledge_base=False, confidence=0.6,
                clarification_question=f"关于“{normalized[:120]}”，请补充已经尝试的步骤、执行后的变化，以及当前完整报错（请先遮盖 API Key 和个人信息），以便继续排查。",
            )
        if any(phrase in folded for phrase in ("你是谁", "你是什么", "介绍一下自己", "who are you", "what are you")):
            intent = Intent.GREETING_IDENTITY
        elif folded.strip(" !！?？。,") in {"你好", "您好", "hello", "hi", "hey"}:
            intent = Intent.GREETING_IDENTITY
        else:
            intent = Intent.SUPPORT_QUESTION
        return QueryUnderstanding(
            intent=intent,
            normalized_query=normalized,
            needs_knowledge_base=intent is Intent.SUPPORT_QUESTION,
            clarification_question="请再详细说明你希望解决的问题。",
            confidence=0.6,
        )

    def generate(self, query: str, evidence: list[Evidence], max_chars: int) -> str:
        official = [item for item in evidence if item.precedence == "P1"]
        historical = [item for item in evidence if item.precedence == "P2"]
        if official:
            lead = official[0]
            answer = lead.text.strip()
            if len(answer) > 700:
                answer = answer[:697].rstrip() + "…"
            suffix = ""
            if historical:
                suffix = "\n\n如果上述说明仍不能解决，可补充客户端、操作步骤和完整报错，以便继续按相似案例排查。"
            return answer + suffix
        lead = historical[0]
        answer = lead.text.strip()
        if len(answer) > 700:
            answer = answer[:697].rstrip() + "…"
        return "以下是历史案例中的排障线索，不能用于确认当前套餐或服务状态：\n\n" + answer


@dataclass
class ResponsesProvider:
    api_key: str
    model: str
    api_base: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0
    name: str = "openai"

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.api_base.rstrip('/')}/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1_000]
            raise GenerationError(f"模型 API 返回 HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GenerationError(f"模型 API 调用失败: {error}") from error

    @staticmethod
    def _output_text(data: dict[str, object]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        chunks: list[str] = []
        for item in data.get("output", []):  # type: ignore[union-attr]
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(str(content["text"]))
        if not chunks:
            raise GenerationError("模型 API 响应中没有 output_text")
        return "\n".join(chunks).strip()

    def understand(self, query: str, context: str) -> QueryUnderstanding:
        schema = {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [item.value for item in Intent],
                },
                "normalized_query": {"type": "string"},
                "needs_knowledge_base": {"type": "boolean"},
                "clarification_question": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": [
                "intent",
                "normalized_query",
                "needs_knowledge_base",
                "clarification_question",
                "confidence",
            ],
            "additionalProperties": False,
        }
        payload = {
            "model": self.model,
            "instructions": INTENT_INSTRUCTIONS,
            "input": json.dumps(
                {"current_message": query, "conversation_context": context},
                ensure_ascii=False,
            ),
            "store": False,
            "max_output_tokens": 500,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "query_understanding",
                    "strict": True,
                    "schema": schema,
                },
                "verbosity": "low",
            },
        }
        try:
            parsed = json.loads(self._output_text(self._request(payload)))
            intent = Intent(parsed["intent"])
            normalized_query = str(parsed["normalized_query"]).strip() or query
            return QueryUnderstanding(
                intent=intent,
                normalized_query=normalized_query,
                needs_knowledge_base=bool(parsed["needs_knowledge_base"]),
                clarification_question=str(parsed["clarification_question"]).strip(),
                confidence=max(0.0, min(1.0, float(parsed["confidence"]))),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GenerationError(f"无法解析模型的请求理解结果: {error}") from error

    def generate(self, query: str, evidence: list[Evidence], max_chars: int) -> str:
        payload = {
            "model": self.model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": build_model_input(query, evidence, max_chars),
            "store": False,
            "max_output_tokens": 900,
            "text": {"verbosity": "low"},
        }
        return self._output_text(self._request(payload))

"""Text generation providers."""

from __future__ import annotations

import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from .models import Evidence, Intent, QueryUnderstanding
from .prompts import INTENT_INSTRUCTIONS, SYSTEM_INSTRUCTIONS, build_model_input


class GenerationError(RuntimeError):
    """Raised when a generation provider cannot produce a response."""

    def __init__(self, message, *, code="model_error", http_status=None):
        super().__init__(message)
        self.code, self.http_status = code, http_status

    def diagnostic(self):
        # Upstream exception text can contain credentials, URLs or customer data.
        messages = {
            "tls_certificate": "TLS 证书校验失败；请安装或更新 certifi，或配置可信的 SSL_CERT_FILE。",
            "timeout": "模型请求超时，请检查网络及服务商响应速度。",
            "network": "无法连接模型服务，请检查网络、DNS 和 API 地址。",
            "http": "模型服务返回 HTTP 错误，请检查密钥、模型权限、接口路径及参数。",
            "invalid_json": "模型未返回符合约定的 JSON 结构。",
            "incomplete": "模型输出达到长度限制，未完成回复。",
            "no_content": "响应没有完整文本，请检查所选接口协议。",
            "refusal": "模型拒绝了本次请求。",
            "quality": "模型回复与业务依据不一致。",
            "model_error": "模型调用或结果校验失败。",
        }
        code = self.code if self.code in messages else "model_error"
        result = {"code": code, "message": messages[code]}
        if isinstance(self.http_status, int) and 100 <= self.http_status <= 599:
            result["http_status"] = self.http_status
        return result


def model_ssl_context():
    """Use trusted CA roots; never disable certificate or hostname verification."""
    context = ssl.create_default_context()
    if not (os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")):
        try:
            import certifi
        except ImportError:
            pass
        else:
            context.load_verify_locations(cafile=certifi.where())
    return context


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
    api_key: str = field(repr=False)
    model: str
    api_base: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0
    name: str = "openai"
    api_mode: ClassVar[str] = "responses"

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        return self._send("responses", payload)

    def _send(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            f"{self.api_base.rstrip('/')}/{endpoint}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "LumenSupportDesk/0.5.0",
            },
            method="POST",
        )
        try:
            options = {"timeout": self.timeout_seconds}
            if self.api_base.startswith("https://"):
                options["context"] = model_ssl_context()
            with urllib.request.urlopen(request, **options) as response:
                result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict):
                    raise GenerationError("模型 API 没有返回 JSON 对象", code="invalid_json")
                return result
        except urllib.error.HTTPError as error:
            # Upstream errors can echo keys or request contents. Expose the code only.
            raise GenerationError(f"模型 API 返回 HTTP {error.code}；请检查地址、密钥、模型权限和接口协议", code="http", http_status=error.code) from error
        except ssl.SSLCertVerificationError as error:
            raise GenerationError("TLS 证书校验失败；可运行 python3 -m pip install -U certifi 后重试", code="tls_certificate") from error
        except (urllib.error.URLError, OSError, ValueError, UnicodeError) as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise GenerationError("TLS 证书校验失败；可运行 python3 -m pip install -U certifi 后重试", code="tls_certificate") from error
            code = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "invalid_json" if isinstance(error, (ValueError, UnicodeError)) else "network"
            raise GenerationError("模型 API 调用失败；请检查网络、服务地址和响应格式", code=code) from error

    @staticmethod
    def _output_text(data: dict[str, object]) -> str:
        if data.get("status") in {"failed", "incomplete", "cancelled"}:
            detail = data.get("incomplete_details") or {}
            code = "incomplete" if isinstance(detail, dict) and detail.get("reason") == "max_output_tokens" else "no_content"
            raise GenerationError("模型 API 未完成输出", code=code)
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        chunks: list[str] = []
        output = data.get("output")
        for item in output if isinstance(output, list) else []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            contents = item.get("content")
            for content in contents if isinstance(contents, list) else []:
                if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        if not chunks:
            raise GenerationError("模型 API 响应中没有 output_text", code="no_content")
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


@dataclass
class ChatCompletionsProvider(ResponsesProvider):
    """Use the same internal prompts and schemas with a Chat Completions endpoint."""

    api_mode: ClassVar[str] = "chat_completions"

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        body = {"model": payload["model"], "store": False,
                "messages": [{"role": "system", "content": payload["instructions"]},
                             {"role": "user", "content": payload["input"]}],
                "max_completion_tokens": payload["max_output_tokens"]}
        output_format = payload.get("text", {}).get("format")
        if output_format:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": output_format["name"], "strict": output_format["strict"],
                "schema": output_format["schema"]}}
        if payload.get("reasoning"):
            body["reasoning_effort"] = payload["reasoning"]["effort"]
        return self._send("chat/completions", body)

    @staticmethod
    def _output_text(data: dict[str, object]) -> str:
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
            message = choice.get("message")
            if isinstance(message, dict) and choice.get("finish_reason") in {None, "stop"}:
                text = message.get("content")
                if isinstance(text, str) and text.strip() and not message.get("refusal"):
                    return text.strip()
        code = "incomplete" if isinstance(choices, list) and choices and isinstance(choices[0], dict) and choices[0].get("finish_reason") == "length" else "no_content"
        raise GenerationError("模型 API 没有返回完整的 message.content", code=code)

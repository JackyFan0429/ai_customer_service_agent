"""Text generation providers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .models import Evidence
from .prompts import SYSTEM_INSTRUCTIONS, build_model_input


class GenerationError(RuntimeError):
    """Raised when a generation provider cannot produce a response."""


class Provider(Protocol):
    name: str

    def generate(self, query: str, evidence: list[Evidence], max_chars: int) -> str: ...


@dataclass
class LocalProvider:
    """Deterministic offline renderer for testing and safe fallback."""

    name: str = "local"

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
class OpenAIProvider:
    api_key: str
    model: str
    api_base: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0
    name: str = "openai"

    def generate(self, query: str, evidence: list[Evidence], max_chars: int) -> str:
        payload = {
            "model": self.model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": build_model_input(query, evidence, max_chars),
            "store": False,
            "max_output_tokens": 900,
            "text": {"verbosity": "low"},
        }
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
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1_000]
            raise GenerationError(f"OpenAI API 返回 HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise GenerationError(f"OpenAI API 调用失败: {error}") from error

        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        chunks: list[str] = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(str(content["text"]))
        if not chunks:
            raise GenerationError("OpenAI API 响应中没有 output_text")
        return "\n".join(chunks).strip()


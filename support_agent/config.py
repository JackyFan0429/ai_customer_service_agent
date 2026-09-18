"""Runtime configuration with safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    corpus_path: Path = Path(__file__).resolve().parent / "demo/corpus.jsonl"
    provider: str = "local"
    model: str | None = None
    api_key: str | None = None
    api_base: str = "https://api.openai.com/v1"
    top_k: int = 8
    min_score: float = 0.08
    max_evidence_chars: int = 8_000
    timeout_seconds: float = 45.0

    @classmethod
    def from_env(cls, **overrides: object) -> "AgentConfig":
        values: dict[str, object] = {
            "corpus_path": Path(os.getenv("SUPPORT_AGENT_CORPUS", cls.corpus_path)),
            "provider": os.getenv("SUPPORT_AGENT_PROVIDER", cls.provider),
            "model": os.getenv("OPENAI_MODEL") or None,
            "api_key": os.getenv("OPENAI_API_KEY") or None,
            "api_base": os.getenv("OPENAI_BASE_URL", cls.api_base).rstrip("/"),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)

    def validate(self) -> None:
        if self.provider not in {"local", "openai"}:
            raise ValueError("provider 必须是 local 或 openai")
        if not self.corpus_path.is_file():
            raise FileNotFoundError(f"找不到检索语料：{self.corpus_path}")
        if self.provider == "openai" and not self.api_key:
            raise ValueError("使用 openai provider 时必须设置 OPENAI_API_KEY")
        if self.provider == "openai" and not self.model:
            raise ValueError("使用 openai provider 时必须设置 OPENAI_MODEL 或传入 --model")

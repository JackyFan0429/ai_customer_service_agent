"""Small in-memory conversation store with bounded history."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    role: str
    text: str


class SessionStore:
    def __init__(self, max_turns: int = 8):
        self._sessions: dict[str, deque[Turn]] = defaultdict(lambda: deque(maxlen=max_turns))

    def add(self, session_id: str, role: str, text: str) -> None:
        self._sessions[session_id].append(Turn(role=role, text=text))

    def contextualize(self, session_id: str | None, query: str) -> str:
        if not session_id or session_id not in self._sessions:
            return query
        history = list(self._sessions[session_id])[-4:]
        compact = "\n".join(f"{turn.role}: {turn.text[:300]}" for turn in history)
        return f"历史对话：\n{compact}\n\n当前问题：{query}"


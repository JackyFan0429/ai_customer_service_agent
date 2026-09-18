"""Small in-memory conversation store with bounded history."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import json
import re

from .retrieval import critical_query_terms, LATIN_OR_CODE_RE


RETRY_RE = re.compile(r"还是|仍然|依然|仍旧|同样|没(?:有)?解决|不奏效|still|didn.t work", re.I)
FOLLOWUP_RE = re.compile(r"^(现在|改成|变成|又|报|错误码|那|还是|仍|依然|也|now\b|still\b|error\b)", re.I)


def resolve_local_query(query: str, previous: str | None) -> tuple[str, bool]:
    """Resolve narrow follow-ups from user text only, without assistant claims.

    Explicit new questions replace the topic. Code-only updates inherit the
    prior subject but replace its code. Failed attempts request more detail.
    This is a conservative offline heuristic, not semantic understanding.
    """
    if not previous:
        return query, False
    codes = critical_query_terms(query)
    old_codes = critical_query_terms(previous)
    words = {t.casefold().rstrip('.+-') for t in LATIN_OR_CODE_RE.findall(query)} - codes
    previous_words = {t.casefold().rstrip('.+-') for t in LATIN_OR_CODE_RE.findall(previous)}
    has_new_subject = bool(words - previous_words - {"now", "still", "error", "it", "is"})
    if RETRY_RE.search(query) and not has_new_subject and (not codes or codes == old_codes):
        return previous, True
    if codes and not has_new_subject and len(query) < 40 and (FOLLOWUP_RE.search(query) or query.strip() in codes):
        # Keep versioned product names; replace only error-shaped identifiers.
        base = LATIN_OR_CODE_RE.sub(
            lambda match: "" if re.fullmatch(r"[a-z]?\d{3,}", match.group().casefold().rstrip('.+-')) else match.group(),
            previous,
        )
        return f"{base.strip()} {' '.join(sorted(codes))}", False
    return query, False


@dataclass(frozen=True)
class Turn:
    role: str
    text: str


class SessionStore:
    def __init__(self, max_turns: int = 8):
        self._sessions: dict[str, deque[Turn]] = defaultdict(lambda: deque(maxlen=max_turns))

    def add(self, session_id: str, role: str, text: str) -> None:
        self._sessions[session_id].append(Turn(role=role, text=text))

    def replace(self, session_id: str, turns: list[Turn]) -> None:
        history: deque[Turn] = deque(maxlen=self._sessions[session_id].maxlen)
        history.extend(turns)
        self._sessions[session_id] = history

    def contextualize(self, session_id: str | None, query: str) -> str:
        history = list(self._sessions.get(session_id, [])) if session_id else []
        active = None
        for turn in history:
            if turn.role == "user":
                active, _ = resolve_local_query(turn.text, active)
        resolved, retry = resolve_local_query(query, active)
        return json.dumps({
            "history": [{"role": t.role, "text": t.text[:300]} for t in history[-8:]],
            "current_question": query,
            "resolved_question": resolved,
            "previous_user_question": active,
            "unresolved_attempt": retry,
        }, ensure_ascii=False)

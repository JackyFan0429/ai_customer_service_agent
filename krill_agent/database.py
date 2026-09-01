"""SQLite persistence for conversations and messages."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class StoredMessage:
    id: int
    conversation_id: str
    role: str
    content: str
    route: str | None
    reason: str | None
    citations: list[dict[str, Any]]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "route": self.route,
            "reason": self.reason,
            "citations": self.citations,
            "created_at": self.created_at,
        }


class ConversationDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    route TEXT,
                    reason TEXT,
                    citations_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS messages_conversation_id_id
                    ON messages(conversation_id, id);
                """
            )

    def create_conversation(self, title: str = "New conversation") -> dict[str, Any]:
        conversation_id = uuid.uuid4().hex
        timestamp = utc_now()
        clean_title = title.strip()[:80] or "New conversation"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, clean_title, timestamp, timestamp),
            )
        return {
            "id": conversation_id,
            "title": clean_title,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_message": None,
            "message_count": 0,
        }

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) AS message_count,
                       (SELECT content FROM messages lm
                        WHERE lm.conversation_id = c.id
                        ORDER BY lm.id DESC LIMIT 1) AS last_message
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_title(self, conversation_id: str, title: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip()[:80] or "New conversation", utc_now(), conversation_id),
            )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        route: str | None = None,
        reason: str | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> StoredMessage:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        timestamp = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages
                    (conversation_id, role, content, route, reason, citations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    route,
                    reason,
                    json.dumps(citations or [], ensure_ascii=False),
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (timestamp, conversation_id),
            )
            message_id = int(cursor.lastrowid)
        return StoredMessage(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            route=route,
            reason=reason,
            citations=citations or [],
            created_at=timestamp,
        )

    def list_messages(self, conversation_id: str) -> list[StoredMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, conversation_id, role, content, route, reason,
                       citations_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [
            StoredMessage(
                id=int(row["id"]),
                conversation_id=str(row["conversation_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                route=row["route"],
                reason=row["reason"],
                citations=json.loads(row["citations_json"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0


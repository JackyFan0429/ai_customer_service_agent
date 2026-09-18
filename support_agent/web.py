"""Small dependency-free HTTP server for the customer support MVP."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .agent import CustomerAgent
from .config import AgentConfig
from .database import ConversationDatabase
from .providers import GenerationError
from .session import Turn


CONVERSATION_RE = re.compile(r"^/api/conversations/([a-f0-9]{32})$")
MESSAGES_RE = re.compile(r"^/api/conversations/([a-f0-9]{32})/messages$")
MAX_BODY_BYTES = 64 * 1024


class WebApplication:
    def __init__(self, agent: CustomerAgent, database: ConversationDatabase):
        self.agent = agent
        self.database = database

    def create_conversation(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return HTTPStatus.CREATED, self.database.create_conversation(str(payload.get("title", "")))

    def list_conversations(self) -> tuple[int, dict[str, Any]]:
        return HTTPStatus.OK, {"conversations": self.database.list_conversations()}

    def get_messages(self, conversation_id: str) -> tuple[int, dict[str, Any]]:
        conversation = self.database.get_conversation(conversation_id)
        if not conversation:
            return HTTPStatus.NOT_FOUND, {"error": "Conversation not found"}
        messages = [item.to_dict() for item in self.database.list_messages(conversation_id)]
        return HTTPStatus.OK, {"conversation": conversation, "messages": messages}

    def send_message(self, conversation_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        conversation = self.database.get_conversation(conversation_id)
        if not conversation:
            return HTTPStatus.NOT_FOUND, {"error": "Conversation not found"}
        content = str(payload.get("content", "")).strip()
        if not content:
            return HTTPStatus.BAD_REQUEST, {"error": "Message content is required"}
        if len(content) > 8_000:
            return HTTPStatus.BAD_REQUEST, {"error": "Message is too long"}

        previous = self.database.list_messages(conversation_id)
        self.agent.sessions.replace(
            conversation_id,
            [Turn(role=item.role, text=item.content) for item in previous[-8:]],
        )
        user_message = self.database.add_message(conversation_id, "user", content)
        if not previous:
            self.database.set_title(conversation_id, content.replace("\n", " ")[:48])
        try:
            result = self.agent.respond(content, session_id=conversation_id)
        except GenerationError as error:
            return HTTPStatus.BAD_GATEWAY, {
                "error": "The model provider could not generate a response",
                "detail": str(error),
                "user_message": user_message.to_dict(),
            }
        assistant_message = self.database.add_message(
            conversation_id,
            "assistant",
            result.answer,
            route=result.route.value,
            reason=result.reason,
            citations=result.citations,
        )
        return HTTPStatus.CREATED, {
            "user_message": user_message.to_dict(),
            "assistant_message": assistant_message.to_dict(),
        }

    def delete_conversation(self, conversation_id: str) -> tuple[int, dict[str, Any]]:
        if not self.database.delete_conversation(conversation_id):
            return HTTPStatus.NOT_FOUND, {"error": "Conversation not found"}
        return HTTPStatus.OK, {"deleted": True}


def make_handler(application: WebApplication, static_dir: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "SupportAgent/0.1"

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} - {format % args}")

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _read_payload(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("Invalid Content-Length") from error
            if length > MAX_BODY_BYTES:
                raise ValueError("Request body is too large")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be an object")
            return parsed

        def _serve_static(self, path: str) -> None:
            filename = "index.html" if path in {"/", "/index.html"} else path.removeprefix("/")
            if filename not in {"index.html", "app.js", "styles.css", "favicon.svg"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            target = static_dir / filename
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/health":
                corpus = application.agent.retriever.corpus
                self._json(HTTPStatus.OK, {
                    "status": "ok", "provider": application.agent.provider.name,
                    "synthetic_demo": bool(corpus) and all(row.get("synthetic") for row in corpus),
                })
                return
            if path == "/api/conversations":
                status, payload = application.list_conversations()
                self._json(status, payload)
                return
            match = MESSAGES_RE.fullmatch(path)
            if match:
                status, payload = application.get_messages(match.group(1))
                self._json(status, payload)
                return
            self._serve_static(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._read_payload()
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            if path == "/api/conversations":
                status, response = application.create_conversation(payload)
                self._json(status, response)
                return
            match = MESSAGES_RE.fullmatch(path)
            if match:
                status, response = application.send_message(match.group(1), payload)
                self._json(status, response)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            match = CONVERSATION_RE.fullmatch(path)
            if not match:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            status, payload = application.delete_conversation(match.group(1))
            self._json(status, payload)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("SUPPORT_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SUPPORT_WEB_PORT", "8080")))
    parser.add_argument("--database", type=Path, default=Path(os.getenv("SUPPORT_AGENT_DB", "runtime/support_agent.db")))
    parser.add_argument("--provider", choices=("local", "openai"))
    parser.add_argument("--model")
    parser.add_argument("--corpus", type=Path)
    return parser.parse_args()


def build_application(args: argparse.Namespace) -> WebApplication:
    config = AgentConfig.from_env(provider=args.provider, model=args.model, corpus_path=args.corpus)
    return WebApplication(CustomerAgent(config), ConversationDatabase(args.database))


def main() -> None:
    args = parse_args()
    application = build_application(args)
    static_dir = Path(__file__).with_name("static")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(application, static_dir))
    print(
        f"AI Customer Support is running at http://{args.host}:{args.port} "
        f"(provider: {application.agent.provider.name})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

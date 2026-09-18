"""Command-line entry point for the AI customer agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import CustomerAgent
from .config import AgentConfig
from .providers import GenerationError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="客户问题；省略后进入交互模式")
    parser.add_argument("--provider", choices=("local", "openai"))
    parser.add_argument("--model", help="模型 ID；也可设置 OPENAI_MODEL")
    parser.add_argument("--corpus", type=Path, help="检索语料 JSONL")
    parser.add_argument("--session-id", default="cli")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    return parser.parse_args()


def print_response(response: object, as_json: bool) -> None:
    data = response.to_dict()  # type: ignore[attr-defined]
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    print(data["answer"])
    if data["citations"]:
        print("\n证据：")
        for item in data["citations"]:
            print(f"- [{item['precedence']}] {item['title']} ({item['document_id']})")
    if data["route"] != "answer":
        print(f"\n处理状态：{data['route']} — {data['reason']}")


def main() -> None:
    args = parse_args()
    config = AgentConfig.from_env(
        provider=args.provider,
        model=args.model,
        corpus_path=args.corpus,
    )
    try:
        agent = CustomerAgent(config)
        if args.query:
            print_response(agent.respond(args.query, session_id=args.session_id), args.json)
            return
        print("智能客服 Agent（输入 exit 退出）")
        while True:
            query = input("\n你：").strip()
            if query.casefold() in {"exit", "quit", "退出"}:
                return
            if query:
                print_response(agent.respond(query, session_id=args.session_id), args.json)
    except (ValueError, FileNotFoundError, GenerationError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()


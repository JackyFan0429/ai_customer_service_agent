"""Repeatable, synthetic workflow checks in an isolated in-memory database."""

from __future__ import annotations

import json
import time

from .service import DeskService
from .storage import DATA, Database, now


def evaluate():
    started = time.perf_counter()
    cases = json.loads((DATA / "evaluation_cases.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        db = Database(":memory:")
        try:
            service = DeskService(db, seed_tickets=False)
            user = db.one("SELECT * FROM users WHERE id=?", (case["user_id"],))
            detail = service.create_ticket(user, {"subject": case["name"], "content": case["messages"][0]})
            for message in case["messages"][1:]:
                detail = service.customer_message(user, detail["ticket"]["id"], {"content": message})
            row = db.one("SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (detail["ticket"]["id"],))
            run = service.decode_run(row)
            names = {t["name"] for t in run["tools"]}
            checks = {"route": run["route"] == case["route"], "tools": set(case["tools"]).issubset(names),
                      "facts": all(phrase in run["answer"] for phrase in case["contains"]),
                      "quality": run["quality"]["passed"],
                      "scope": all(t["result"].get("id", case["user_id"]) == case["user_id"] for t in run["tools"] if t["name"] == "get_account_overview")}
            if case.get("action"):
                checks["action"] = any(a["type"] == case["action"] for a in run["actions"])
            if case.get("no_action"):
                checks["no_action"] = not run["actions"]
            if case.get("not_contains"):
                checks["no_repeated_or_unsupported_content"] = all(phrase not in run["answer"] for phrase in case["not_contains"])
            if case.get("tools_absent"):
                checks["no_irrelevant_queries"] = not set(case["tools_absent"]).intersection(names)
            results.append({"id": case["id"], "name": case["name"], "family": case["family"], "passed": all(checks.values()),
                            "checks": checks, "route": run["route"], "expected_route": case["route"], "tool_count": len(run["tools"])})
        except Exception as error:
            results.append({"id": case["id"], "name": case["name"], "family": case["family"], "passed": False, "error": type(error).__name__})
        finally:
            db.close()
    return {"suite": "lumen-workflow-v1", "total": len(results), "passed": sum(r["passed"] for r in results),
            "results": results, "created_at": now(), "duration_ms": round((time.perf_counter()-started)*1000),
            "provider": "local", "dataset": "按日志可观察流程改写的合成场景",
            "limitation": "开发回归集；不是独立盲测、真实模型评测或线上解决率；没有使用客户原始文本。"}

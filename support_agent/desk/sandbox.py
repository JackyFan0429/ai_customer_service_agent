"""A tiny local API business: requests, quota consumption, and failure records."""

import json

from .service import DeskError, is_staff
from .storage import DATA, now


def simulate_request(db, user, payload):
    if is_staff(user):
        raise DeskError("请使用客户账号体验模型请求", 403)
    models = {m["id"] for m in json.loads((DATA / "model_catalog.json").read_text(encoding="utf-8"))}
    model, scenario = payload.get("model"), payload.get("scenario", "normal")
    if not isinstance(model, str) or not isinstance(scenario, str) or model not in models or scenario not in {"normal", "upstream_error", "auth_error"}:
        raise DeskError("请选择目录中的模型与演示场景")
    uid = user["id"]  # Never accept an owner from the request body.
    channel_id = "reasoning" if model.startswith("claude") else "image" if model.startswith("grok") else "standard"
    with db.transaction():
        channel = db.one("SELECT * FROM platform_status WHERE id=?", (channel_id,))
        account = db.one("SELECT * FROM users WHERE id=?", (uid,))
        sub = db.one("SELECT * FROM subscriptions WHERE user_id=? AND status='active' AND expires_at>? AND quota_units-used_units>=1200 ORDER BY id LIMIT 1", (uid, now()))
        code, error, cost, note = 200, "", 0, ""
        if scenario == "auth_error":
            code, error = 401, "invalid_api_key"
        elif account["balance_units"] < 0:
            code, error = 403, "negative_balance"
        elif scenario == "upstream_error" or channel["status"] != "operational":
            code, error = 503, "upstream_unavailable"
        elif not sub:
            code, error = 403, "quota_exhausted_balance_fallback_disabled"
        else:
            cost = 1200
            db.execute("UPDATE subscriptions SET used_units=used_units+? WHERE id=?", (cost, sub["id"]))
            note = "本次成功请求消耗演示套餐额度 $0.1200。"
        rid = db.execute("INSERT INTO request_logs(user_id,model,channel,status_code,error,cost_units,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (uid, model, channel["name"], code, error, cost, 1250 if code == 200 else 300, now()))
        descriptions = {"invalid_api_key": "模拟 Key 鉴权失败。", "negative_balance": "账户存在负余额，演示请求被拦截。",
                        "upstream_unavailable": "演示上游暂时不可用。", "quota_exhausted_balance_fallback_disabled": "套餐额度不足，且演示 Key 未开启余额兜底。"}
        db.event(None, "sandbox_request", f"客户 #{uid} 的 {model} 演示请求 #{rid} 返回 {code}", uid)
        return {"request_id": rid, "model": model, "channel": channel["name"], "status_code": code,
                "error": error, "cost_units": cost, "simulation": True,
                "message": note or descriptions[error] + "本次失败请求未扣费。", "created_at": now()}

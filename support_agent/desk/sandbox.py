"""A tiny local API business: requests, quota consumption, and failure records."""

import json

from .service import DeskError, is_staff
from .storage import DATA, now
from .billing import refresh_subscriptions


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
        refresh_subscriptions(db, uid)
        channel = db.one("SELECT * FROM platform_status WHERE id=?", (channel_id,))
        account = db.one("SELECT * FROM users WHERE id=?", (uid,))
        sub = db.one("SELECT * FROM subscriptions WHERE user_id=? AND status='active' AND expires_at>? AND quota_units-used_units>=1200 ORDER BY id LIMIT 1", (uid, now()))
        key_id = payload.get('key_id')
        if key_id is not None and type(key_id) is not int:
            raise DeskError('请选择有效 Key')
        key = db.one('SELECT * FROM api_key_metadata WHERE user_id=?' + (' AND id=?' if key_id is not None else '') + ' ORDER BY id LIMIT 1', (uid, key_id) if key_id is not None else (uid,))
        if not key:
            raise DeskError('当前账号没有该 Key', 404)
        code, error, cost, note, billing_source = 200, "", 0, "", "none"
        stamp = now()
        if account["status"] != "active":
            code, error = 403, "account_disabled"
        elif scenario == "auth_error":
            code, error = 401, "invalid_api_key"
        elif account["balance_units"] < 0:
            code, error = 403, "negative_balance"
        elif scenario == "upstream_error" or channel["status"] != "operational":
            code, error = 503, "upstream_unavailable"
        elif sub:
            cost, billing_source = 1200, 'subscription'
            db.execute("UPDATE subscriptions SET used_units=used_units+? WHERE id=?", (cost, sub["id"]))
            note = "本次成功请求消耗演示套餐额度 $0.1200，未扣账户余额。"
        elif not key['balance_fallback']:
            code, error = 403, "quota_exhausted_balance_fallback_disabled"
        elif account['balance_units'] < 1200:
            code, error = 403, "insufficient_balance"
        else:
            cost, billing_source = 1200, 'balance'
            db.execute('UPDATE users SET balance_units=balance_units-? WHERE id=?', (cost, uid))
            note = "本次成功请求通过已开启的余额兜底扣款 $0.1200。"
        rid = db.execute("INSERT INTO request_logs(user_id,model,channel,status_code,error,cost_units,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (uid, model, channel["name"], code, error, cost, 1250 if code == 200 else 300, now()))
        db.execute('UPDATE request_logs SET billing_source=?,api_key_id=?,subscription_id=?,created_at=? WHERE id=?', (billing_source, key['id'], sub['id'] if billing_source == 'subscription' else None, stamp, rid))
        if billing_source == 'balance':
            db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,operation_key,created_at) VALUES (?,'request_charge',?,?,?,?,?)", (uid, -cost, account['balance_units']-cost, f'请求 #{rid} 余额兜底扣款', f'request:{rid}', stamp))
        elif billing_source == 'subscription':
            db.execute("INSERT INTO quota_ledger(user_id,subscription_id,kind,delta_units,used_after_units,request_id,period_end,created_at) VALUES (?,?,'request',?,?,?,?,?)", (uid, sub['id'], cost, sub['used_units']+cost, rid, sub['reset_at'], stamp))
        descriptions = {"account_disabled": "账号已停用。", "insufficient_balance": "套餐额度不足且账户余额不足以支付本次请求，请充值。","invalid_api_key": "模拟 Key 鉴权失败。", "negative_balance": "账户存在负余额，演示请求被拦截。",
                        "upstream_unavailable": "演示上游暂时不可用。", "quota_exhausted_balance_fallback_disabled": "套餐额度不足，且演示 Key 未开启余额兜底。"}
        db.event(None, "sandbox_request", f"客户 #{uid} 的 {model} 演示请求 #{rid} 返回 {code}", uid)
        return {"request_id": rid, "model": model, "channel": channel["name"], "status_code": code,
                "error": error, "cost_units": cost, "simulation": True,
                "message": note or descriptions[error] + "本次失败请求未扣费。", "created_at": stamp, "billing_source": billing_source, "api_key_id": key["id"]}

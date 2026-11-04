"""Account-bound read tools. Models never receive a database handle or user selector."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .knowledge import retrieve
from .storage import Database, now
from .request_context import QUERY_KEYS, lookup


def money(units: int) -> str:
    return f"${units / 10000:,.4f}"


def display_times(value: str) -> dict:
    """Explicit timezone conversions are query evidence, not model arithmetic."""
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return {}
    values = {'UTC': instant.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')}
    for name in ('Asia/Shanghai', 'Australia/Sydney'):
        try:
            values[name] = instant.astimezone(ZoneInfo(name)).strftime('%Y-%m-%d %H:%M %z')
        except ZoneInfoNotFoundError:
            pass  # UTC remains usable on installations without the timezone DB.
    return values


class BusinessTools(Protocol):
    """Replace this adapter to connect the same workflow to another backend."""

    def call(self, name: str, **arguments) -> dict: ...


TOOL_DESCRIPTIONS = {
    "get_account_overview": "查询当前工单用户的账户状态和余额",
    "get_subscriptions": "查询有效套餐、周期额度与刷新时间",
    "get_orders": "查询支付订单与退款申请状态",
    "get_invoices": "查询发票与关联订单",
    "get_recent_requests": "按请求编号或时间范围核查当前客户请求；无定位条件时查询最近 24 小时摘要",
    "check_platform_status": "查询本地演示平台的当前渠道状态",
    "get_api_keys": "查询 Key 名称、线路与末四位，不返回密钥",
    "get_user_ticket_history": "查询当前用户的其他工单状态",
    "check_balance_adjustment": "核验余额回正条件，仅查询、不写入",
    "search_kb": "检索审核期限内的已发布知识",
}


def balance_eligibility(db: Database, user_id: int, settings: dict) -> dict:
    user = db.one("SELECT balance_units FROM users WHERE id=?", (user_id,))
    balance = user["balance_units"]
    result = {"eligible": False, "balance_units": balance, "reason": "余额没有欠费"}
    if balance >= 0:
        return result
    threshold = settings.get("balance_fix_threshold_units", 50000)
    if -balance > threshold:
        cutoff = (datetime.fromisoformat(now()) - timedelta(days=7)).isoformat(timespec="seconds")
        previous = db.one("SELECT id FROM ledger WHERE user_id=? AND kind='balance_fix' AND delta_units>? AND julianday(created_at)>=julianday(?) AND julianday(created_at)<=julianday(?)", (user_id, threshold, cutoff, now()))
        if previous:
            return {**result, "reason": "过去 7 天内已成功回正过超过 5 美元的欠款，本次不能再次回正；请小额充值补足当前欠款"}
    latest = db.one("SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    if not latest or latest["kind"] != "request_overage" or latest["balance_after_units"] != balance or latest["delta_units"] != balance:
        return {**result, "reason": "负余额与最近一笔套餐超额扣费不匹配，需要人工核账"}
    return {**result, "eligible": True, "reason": "满足演示规则，可执行回正", "ledger_id": latest["id"]}


class LocalBusinessTools:
    def __init__(self, db: Database, user_id: int, ticket_id: int, *, max_calls=8):
        self.db, self.user_id, self.ticket_id = db, user_id, ticket_id
        self.max_calls = max_calls
        self.trace: list[dict] = []
        self.cache = {}

    def call(self, name: str, **arguments) -> dict:
        if name not in TOOL_DESCRIPTIONS:
            raise ValueError("未知工具")
        if set(arguments) - ({"query"} if name == "search_kb" else QUERY_KEYS if name == "get_recent_requests" else set()):
            raise ValueError("工具参数不允许指定其他用户或执行写入")
        key = (name, json.dumps(arguments, sort_keys=True))
        if key in self.cache:
            return self.cache[key]
        if len(self.trace) >= self.max_calls:
            raise ValueError("本次工具查询次数已达上限")
        result = self._query(name, arguments)
        self.trace.append({"name": name, "description": TOOL_DESCRIPTIONS[name], "arguments": arguments,
                           "result": result, "status": "ok", "queried_at": now()})
        self.cache[key] = result
        return result

    def _query(self, name: str, arguments: dict) -> dict:
        uid, db = self.user_id, self.db
        if name == "get_account_overview":
            return db.one("SELECT id,name,status,balance_units,persona FROM users WHERE id=?", (uid,))
        if name == "get_subscriptions":
            rows = db.all("SELECT id,name,quota_units,used_units,reset_at,expires_at,status FROM subscriptions WHERE user_id=? ORDER BY (status='active') DESC,id DESC", (uid,))
            for row in rows:
                row["remaining_units"] = max(0, row["quota_units"] - row["used_units"]) if row["expires_at"] > now() and row["status"] == "active" else 0
                row['reset_display_times'] = display_times(row['reset_at'])
                row['expiry_display_times'] = display_times(row['expires_at'])
            return {"subscriptions": rows}
        if name == "get_orders":
            return {"orders": db.all("SELECT number,item,amount_cents,status,refund_status,paid_at FROM orders WHERE user_id=? ORDER BY id DESC", (uid,))}
        if name == "get_invoices":
            return {"invoices": db.all("SELECT i.id,i.order_id,o.number AS order_number,i.title,i.amount_cents,i.status,i.created_at,i.updated_at,i.reissued_from FROM invoices i LEFT JOIN orders o ON o.id=i.order_id WHERE i.user_id=? ORDER BY i.id DESC", (uid,))}
        if name == "get_recent_requests":
            return lookup(db, uid, arguments, queried_at=now())
        if name == "check_platform_status":
            return {"channels": db.all("SELECT * FROM platform_status"), "queried_at": now(), "source": "local_demo_database"}
        if name == "get_api_keys":
            return {"keys": db.all("SELECT id,name,suffix,channel,balance_fallback FROM api_key_metadata WHERE user_id=?", (uid,))}
        if name == "get_user_ticket_history":
            return {"tickets": db.all("SELECT id,subject,status,created_at FROM tickets WHERE user_id=? AND id<>? ORDER BY id DESC LIMIT 5", (uid, self.ticket_id))}
        if name == "check_balance_adjustment":
            return balance_eligibility(db, uid, db.settings())
        rows = db.all("SELECT * FROM knowledge WHERE published=1 AND review_after>=?", (now()[:10],))
        corpus = [{"document_id": r["id"], "title": r["title"], "text": r["content"], "categories": [r["category"]],
                   "keywords": json.loads(r["keywords"]), "precedence": "P1"} for r in rows]
        return retrieve(corpus, str(arguments.get("query", ""))[:2000])

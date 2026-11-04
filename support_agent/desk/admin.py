"""Administrator operations for the local business and support configuration."""

from __future__ import annotations

import json
import re

from .service import DeskError, public_user, require_admin, require_support, text_field
from .storage import DATA, after, encode, now, password_hash
from .audit import usage_summary, valid_prices


class AdminConsole:
    def __init__(self, service):
        self.service, self.db = service, service.db

    def dashboard(self, user):
        require_support(user)
        db = self.db
        tickets = self.service.list_tickets(user)
        return {"metrics": {
            "total_tickets": len(tickets),
            "pending_review": db.one("SELECT COUNT(*) AS n FROM runs WHERE state='draft'")["n"],
            "waiting_human": sum(t["status"] in {"waiting_human", "human"} for t in tickets),
            "resolved": sum(t["status"] == "resolved" for t in tickets),
            "sent_replies": db.one("SELECT COUNT(*) AS n FROM runs WHERE state='sent'")["n"],
            "customer_count": db.one("SELECT COUNT(*) AS n FROM users WHERE role='personal'")["n"],
            "overdue": sum(bool(t["status"] == "waiting_human" and t["handoff_at"] and t["handoff_at"] < after(hours=-db.settings()["handoff_reminder_hours"])) for t in tickets),
        }, "tickets": tickets, "events": self.service.visible_events(user, db.all("SELECT e.*,t.subject FROM events e LEFT JOIN tickets t ON t.id=e.ticket_id ORDER BY e.id DESC LIMIT 15")),
            "settings": {k: v for k, v in db.settings().items() if user['role'] == 'admin' or k != 'model_prices'}, "provider": "openai" if self.service.workflow.model else "local",
            "model": self.service.workflow.model.provider.model if self.service.workflow.model else None,
            "platform": db.all("SELECT * FROM platform_status")}

    def usage(self, user):
        require_admin(user)
        runs = [self.service.decode_run(r) for r in self.db.all('SELECT * FROM runs')]
        return usage_summary(runs, self.db.settings().get('model_prices'))

    def users(self, user):
        require_admin(user)
        return [public_user(r) for r in self.db.all("SELECT * FROM users ORDER BY id")]

    def create_user(self, user, payload):
        require_admin(user)
        email = text_field(payload, "email", maximum=160).lower()
        name = text_field(payload, "name", maximum=60)
        password = payload.get("password", "")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise DeskError("请输入有效邮箱")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise DeskError("密码长度应为 8–128 位")
        if self.db.one("SELECT id FROM users WHERE email=?", (email,)):
            raise DeskError("该邮箱已存在", 409)
        uid = self.db.execute("INSERT INTO users(email,name,password_hash,role,created_at) VALUES (?,?,?,'personal',?)", (email, name, password_hash(password), now()))
        self.db.event(None, "account_created", f"创建客户账号 #{uid}", user["id"])
        return self.service.account(user, uid)

    def update_user(self, user, uid, payload):
        require_admin(user)
        target = self.db.one("SELECT * FROM users WHERE id=?", (uid,))
        if not target:
            raise DeskError("账号不存在", 404)
        if target["role"] == "admin":
            raise DeskError("演示管理员账号不在客户管理中修改")
        with self.db.transaction():
            if "name" in payload:
                self.db.execute("UPDATE users SET name=? WHERE id=?", (text_field(payload, "name", maximum=60), uid))
            if "status" in payload:
                if payload["status"] not in {"active", "disabled"}:
                    raise DeskError("无效账号状态")
                self.db.execute("UPDATE users SET status=? WHERE id=?", (payload["status"], uid))
                if payload["status"] == "disabled":
                    self.db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            if "password" in payload:
                password = payload["password"]
                if not isinstance(password, str) or not 8 <= len(password) <= 128:
                    raise DeskError("密码长度应为 8–128 位")
                self.db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(password), uid))
                self.db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            if "balance_units" in payload:
                units = payload["balance_units"]
                if type(units) is not int or not -100000000 <= units <= 10000000000:
                    raise DeskError("无效余额")
                if units != target["balance_units"]:
                    self.db.execute("UPDATE users SET balance_units=? WHERE id=?", (units, uid))
                    self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (?,'admin_adjustment',?,?,?,?)", (uid, units-target["balance_units"], units, "管理员调整演示余额", now()))
            if "quota_units" in payload or "used_units" in payload:
                sub = self.db.one("SELECT * FROM subscriptions WHERE user_id=? ORDER BY (status='active') DESC,id DESC LIMIT 1", (uid,))
                quota = payload.get("quota_units", sub["quota_units"] if sub else 6000000)
                used = payload.get("used_units", sub["used_units"] if sub else 0)
                if type(quota) is not int or type(used) is not int or not 0 <= used <= quota <= 10000000000:
                    raise DeskError("已用额度必须介于 0 与总额度之间")
                if sub:
                    self.db.execute("UPDATE subscriptions SET quota_units=?,used_units=? WHERE id=?", (quota, used, sub["id"]))
                else:
                    self.db.execute("INSERT INTO subscriptions(user_id,name,quota_units,used_units,reset_at,expires_at) VALUES (?,'演示套餐',?,?,?,?)", (uid, quota, used, after(days=7), after(days=30)))
            self.db.event(None, "account_updated", f"更新客户 #{uid} 的演示资料", user["id"])
        return self.service.account(user, uid)

    def save_subscription(self, user, uid, payload, sid=None):
        require_admin(user)
        if not self.db.one("SELECT id FROM users WHERE id=?", (uid,)):
            raise DeskError("账号不存在", 404)
        old = self.db.one("SELECT * FROM subscriptions WHERE id=? AND user_id=?", (sid, uid)) if sid else None
        if sid and not old:
            raise DeskError("套餐不存在", 404)
        values = {**(old or {}), **payload}
        period = values.get('period_days', 7)
        if type(period) is not int or not 1 <= period <= 366:
            raise DeskError('刷新周期应为 1–366 天')
        name = text_field(values, "name", maximum=80)
        quota, used = values.get("quota_units"), values.get("used_units", 0)
        if type(quota) is not int or type(used) is not int or not 0 <= used <= quota <= 10000000000:
            raise DeskError("已用额度必须介于 0 与总额度之间")
        status = values.get("status", "active")
        if status not in {"active", "expired", "cancelled"}:
            raise DeskError("无效套餐状态")
        from datetime import datetime, timezone
        dates = []
        for field in ("reset_at", "expires_at"):
            try:
                value = datetime.fromisoformat(values.get(field, ""))
                if not value.tzinfo:
                    value = value.replace(tzinfo=timezone.utc)
                dates.append(value.astimezone(timezone.utc).isoformat(timespec="seconds"))
            except (ValueError, TypeError):
                raise DeskError("请输入有效的套餐刷新和到期时间")
        with self.db.transaction():
            if status == "active":
                self.db.execute("UPDATE subscriptions SET status='cancelled' WHERE user_id=? AND status='active' AND id!=?", (uid, sid or -1))
            if sid:
                self.db.execute("UPDATE subscriptions SET name=?,quota_units=?,used_units=?,reset_at=?,expires_at=?,status=? WHERE id=? AND user_id=?", (name, quota, used, *dates, status, sid, uid))
            else:
                sid = self.db.execute("INSERT INTO subscriptions(user_id,name,quota_units,used_units,reset_at,expires_at,status) VALUES (?,?,?,?,?,?,?)", (uid, name, quota, used, *dates, status))
            self.db.execute('UPDATE subscriptions SET period_days=? WHERE id=?', (period, sid))
            self.db.event(None, "subscription_updated", f"管理员{'修改' if sid else '新增'}客户 #{uid} 的套餐：{name}", user["id"])
        return self.service.account(user, uid)

    def settings(self, user, payload):
        require_admin(user)
        validators = {
            "reply_mode": lambda v: v in {"review", "auto"},
            "human_cooldown_minutes": lambda v: type(v) is int and 1 <= v <= 1440,
            "handoff_reminder_hours": lambda v: type(v) is int and 1 <= v <= 168,
            "max_tool_calls": lambda v: type(v) is int and 4 <= v <= 16,
            "auto_balance_fix": lambda v: type(v) is bool,
            "model_prices": valid_prices,
        }
        for key, value in payload.items():
            if key not in validators or not validators[key](value):
                raise DeskError(f"无效配置：{key}")
        with self.db.transaction():
            for key, value in payload.items():
                self.db.set_setting(key, value)
            if payload.get("reply_mode") == "review":
                self.db.execute("UPDATE tickets SET status='waiting_human',updated_at=? WHERE id IN (SELECT ticket_id FROM generation_jobs WHERE force_review=0 AND state IN ('queued','running'))", (now(),))
                self.db.execute("UPDATE generation_jobs SET state='cancelled' WHERE force_review=0 AND state IN ('queued','running')")
            self.db.event(None, "policy_updated", "管理员更新客服工作流配置", user["id"])
        return self.db.settings()

    def invoice(self, user, ticket_id, invoice_id, payload):
        require_support(user)
        ticket = self.service.ticket(user, ticket_id)
        action = payload.get('action')
        if action not in {'edit', 'reissue'}:
            raise DeskError('请选择修改或重开')
        with self.db.transaction():
            old = self.db.one('SELECT * FROM invoices WHERE id=? AND user_id=?', (invoice_id, ticket['user_id']))
            if not old:
                raise DeskError('该客户没有此发票', 404)
            order = self.db.one('SELECT * FROM orders WHERE id=? AND user_id=?', (old['order_id'], ticket['user_id']))
            if not order or payload.get('order_number') != order['number'] or payload.get('order_verified') is not True:
                raise DeskError('请核对并确认该客户的关联订单', 409)
            if old['status'] == 'cancelled':
                raise DeskError('原发票已取消，请使用最新发票记录', 409)
            if type(payload.get('expected_revision')) is not int or payload['expected_revision'] != old['revision']:
                raise DeskError('发票已更新，请查看最新记录后再操作', 409)
            title = text_field(payload, 'title', maximum=120)
            amount = payload.get('amount_cents', old['amount_cents'])
            if type(amount) is not int or not 0 < amount <= 100000000:
                raise DeskError('请输入有效发票金额')
            if amount != old['amount_cents']:
                require_admin(user)
            stamp = now()
            if action == 'reissue':
                self.db.execute("UPDATE invoices SET status='cancelled',revision=revision+1,updated_at=? WHERE id=?", (stamp, invoice_id))
                result_id = self.db.execute("INSERT INTO invoices(user_id,order_id,title,amount_cents,status,created_at,updated_at,reissued_from) VALUES (?,?,?,?,'issued',?,?,?)",
                                            (ticket['user_id'], order['id'], title, amount, stamp, stamp, invoice_id))
            else:
                result_id = invoice_id
                self.db.execute('UPDATE invoices SET title=?,amount_cents=?,revision=revision+1,updated_at=? WHERE id=?', (title, amount, stamp, invoice_id))
            updated = self.db.one('SELECT * FROM invoices WHERE id=?', (result_id,))
            self.db.execute('INSERT INTO invoice_events(invoice_id,actor_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)',
                            (invoice_id, user['id'], action, encode(old), encode(updated), stamp))
            description = '已完成本地演示重开，原记录已取消' if action == 'reissue' else '已更新本地演示发票资料'
            status = {'pending': '待开具', 'issued': '已开具', 'cancelled': '已取消'}[updated['status']]
            message = f"{description}：抬头「{title}」，金额 ¥{amount/100:.2f}，状态「{status}」。未发送邮件，不涉及真实开票。"
            self.db.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at) VALUES (?,?,'human',?,?)", (ticket_id, user['id'], message, stamp))
            self.db.execute("UPDATE tickets SET updated_at=?,status='waiting_customer',human_until=?,handoff_at=NULL,reminder_at=NULL WHERE id=?", (stamp, after(minutes=self.db.settings()['human_cooldown_minutes']), ticket_id))
            self.db.execute("UPDATE runs SET state='superseded' WHERE ticket_id=? AND state='draft'", (ticket_id,))
            self.service.cancel_jobs(ticket_id)
            self.db.event(ticket_id, 'invoice_updated', f"客服处理发票 #{invoice_id}；结果 #{result_id}，操作 {action}", user['id'])
        return self.service.ticket_detail(user, ticket_id)

    def save_knowledge(self, user, payload):
        require_admin(user)
        doc_id = text_field(payload, "id", maximum=40)
        if not re.fullmatch(r"[A-Z0-9_-]+", doc_id):
            raise DeskError("知识 ID 使用大写字母、数字、下划线或连字符")
        title = text_field(payload, "title", maximum=120)
        content = text_field(payload, "content", maximum=10000)
        category = text_field(payload, "category", maximum=30)
        deadline = text_field(payload, "review_after", maximum=10)
        from datetime import date
        try:
            date.fromisoformat(deadline)
        except ValueError:
            raise DeskError("请输入有效的复核日期")
        keywords = payload.get("keywords", [])
        if not isinstance(keywords, list) or len(keywords)>30 or any(not isinstance(k, str) or len(k)>60 for k in keywords):
            raise DeskError("关键词格式不正确")
        if type(payload.get("published", True)) is not bool:
            raise DeskError("发布状态必须是布尔值")
        self.db.execute("INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content,category=excluded.category,keywords=excluded.keywords,published=excluded.published,review_after=excluded.review_after,updated_at=excluded.updated_at",
                        (doc_id, title, content, category, encode(keywords), int(payload.get("published", True)), deadline, now()))
        self.db.event(None, "knowledge_updated", f"更新知识 {doc_id}", user["id"])
        return {"saved": True}

    def knowledge(self, user):
        require_admin(user)
        rows = self.db.all("SELECT * FROM knowledge ORDER BY category,id")
        for r in rows:
            r["keywords"] = json.loads(r["keywords"])
            r["current"] = r["review_after"] >= now()[:10]
        return rows

    def refund(self, user, oid, payload):
        require_admin(user)
        status = payload.get("status")
        if status not in {"approved", "rejected"}:
            raise DeskError("请选择批准或拒绝")
        order = self.db.one("SELECT * FROM orders WHERE id=?", (oid,))
        if not order:
            raise DeskError("订单不存在", 404)
        self.db.execute("UPDATE orders SET refund_status=? WHERE id=?", (status, oid))
        self.db.event(None, "demo_refund_review", f"订单 {order['number']} 的本地退款记录已设为 {status}，未连接支付系统", user["id"])
        return {"updated": True, "simulation": True}

    def platform(self, user, channel_id, payload):
        require_admin(user)
        if payload.get("status") not in {"operational", "degraded", "outage"}:
            raise DeskError("无效渠道状态")
        if not self.db.one("SELECT id FROM platform_status WHERE id=?", (channel_id,)):
            raise DeskError("渠道不存在", 404)
        self.db.execute("UPDATE platform_status SET status=?,detail=?,updated_at=? WHERE id=?", (payload["status"], text_field(payload, "detail", maximum=300), now(), channel_id))
        self.db.event(None, "platform_updated", f"更新演示渠道 {channel_id}", user["id"])
        return {"updated": True}

    def learning(self, user):
        require_admin(user)
        profile_path = DATA / "source_profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
        report = self.db.one("SELECT * FROM evaluation_reports ORDER BY id DESC LIMIT 1")
        return {"profile": profile, "evaluation": json.loads(report["result_json"]) if report else None,
                "settings": self.db.settings(), "models": json.loads((DATA / "model_catalog.json").read_text(encoding="utf-8"))}

"""Business operations, authorization, draft publication, and human handoff."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from .engine import INTENT_LABELS, SupportWorkflow, quality_check, scrub
from .storage import DATA, Database, after, encode, now, password_hash, password_matches
from .tools import balance_eligibility
from .billing import refresh_subscriptions
from .audit import run_receipt
from .request_context import parse_context, time_evidence


class DeskError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def public_user(row):
    return {k: v for k, v in row.items() if k not in {"password_hash", "token_hash", "csrf", "expires_at"}}


def require_admin(user):
    if user["role"] != "admin" or not is_staff(user):
        raise DeskError("需要管理员权限", 403)


def is_staff(user):
    return user["role"] in {"admin", "support"} and user.get("view_mode", "workspace") == "workspace"


def require_support(user):
    if not is_staff(user):
        raise DeskError("需要客服工作台权限", 403)


def text_field(payload, key, *, maximum=6000, required=True):
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise DeskError(f"{key} 必须是文字")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise DeskError(f"{key} 不能为空且不得超过 {maximum} 字")
    return scrub(value)


class DeskService:
    def __init__(self, db: Database, model=None, *, seed_tickets=True, background=False):
        self.db = db
        refresh_subscriptions(db)
        self.workflow = SupportWorkflow(db, model)
        self.model_status = {"status": "configured" if model else "local"}
        self.background = False
        self.seeding = False
        if seed_tickets and not db.settings().get("examples_seeded"):
            self.seed_examples()
        self.background = background

    def login(self, email, password):
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > 256:
            raise DeskError("邮箱或密码不正确", 401)
        user = self.db.one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
        if not user or not password_matches(password, user["password_hash"]) or user["status"] != "active":
            raise DeskError("邮箱或密码不正确，或账号已停用", 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.db.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
        user["view_mode"] = "workspace" if user["role"] in {"admin", "support"} else "personal"
        self.db.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at,view_mode) VALUES (?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, after(hours=12), user["view_mode"]))
        return {"user": public_user(user), "csrf": csrf}, token

    def authenticate(self, token):
        digest = hashlib.sha256(str(token).encode()).hexdigest()
        row = self.db.one("SELECT u.*,s.csrf,s.view_mode FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.status='active'", (digest, now()))
        if not row:
            raise DeskError("请先登录", 401)
        return row

    def logout(self, token):
        self.db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def switch_view(self, user, mode):
        if mode not in {"personal", "workspace"} or (mode == "workspace" and user["role"] not in {"admin", "support"}):
            raise DeskError("当前账号不能切换到该空间", 403)
        self.db.execute("UPDATE sessions SET view_mode=? WHERE user_id=? AND csrf=?", (mode, user["id"], user["csrf"]))
        return {"user": public_user({**user, "view_mode": mode})}

    def ticket(self, user, ticket_id):
        row = self.db.one("SELECT t.*,u.name AS customer_name,u.email AS customer_email FROM tickets t JOIN users u ON t.user_id=u.id WHERE t.id=?", (ticket_id,))
        if not row or (not is_staff(user) and row["user_id"] != user["id"]):
            raise DeskError("工单不存在", 404)
        return row

    def list_tickets(self, user):
        clause, args = ("", ()) if is_staff(user) else ("WHERE t.user_id=?", (user["id"],))
        rows = self.db.all(f"SELECT t.*,u.name AS customer_name,u.email AS customer_email,"
                           "(SELECT CASE WHEN retracted_at IS NOT NULL THEN '已撤回' ELSE content END FROM messages m WHERE m.ticket_id=t.id AND m.visibility='public' ORDER BY id DESC LIMIT 1) AS preview,"
                           "(SELECT COUNT(*) FROM runs r WHERE r.ticket_id=t.id AND r.state='draft') AS draft_count "
                           f"FROM tickets t JOIN users u ON u.id=t.user_id {clause} ORDER BY t.updated_at DESC,t.id DESC", args)
        for row in rows:
            row.pop("context_json", None)
            if not is_staff(user):
                row.pop("draft_count", None)
        return rows

    def ticket_detail(self, user, ticket_id):
        ticket = self.ticket(user, ticket_id)
        visible = ('public', 'staff', 'admin') if is_staff(user) and user['role'] == 'admin' else ('public', 'staff') if is_staff(user) else ('public',)
        marks = ','.join('?' for _ in visible)
        messages = self.db.all(f"SELECT m.*,u.name AS author_name,r.provider AS run_provider,r.quality_json AS run_quality FROM messages m LEFT JOIN users u ON m.author_id=u.id LEFT JOIN runs r ON r.id=m.run_id WHERE m.ticket_id=? AND m.visibility IN ({marks}) ORDER BY m.id", (ticket_id, *visible))
        for message in messages:
            message["request_context"] = json.loads(message.pop("request_context_json", "{}"))
            provider = message.pop("run_provider")
            metadata = json.loads(message.pop("run_quality") or "{}").get("model", {})
            if message["role"] == "assistant":
                message["reply_source"] = "model" if provider == "openai" and metadata.get("source") == "model" else "unrecorded" if provider == "openai" and not metadata else "policy" if metadata.get("source") == "policy" else "local"
                completed = [c for c in metadata.get("calls", []) if c.get("stage") == "support_reply" and c.get("ok")]
                message["reply_model"] = (completed[-1].get("response_model") or metadata.get("requested_model", "")) if completed and message["reply_source"] == "model" else ""
            if message["retracted_at"]:
                message["content"] = "已撤回"
        result = {"ticket": {k: v for k, v in ticket.items() if k != "context_json"}, "messages": messages}
        result["human_priority"] = bool(self.human_notice(ticket))
        job = self.db.one("SELECT id,state,due_at,force_review FROM generation_jobs WHERE ticket_id=? AND state IN ('queued','running') ORDER BY id DESC LIMIT 1", (ticket_id,))
        result["reply_state"] = "suggestion_pending" if job and job["force_review"] else "generating" if job else "idle"
        if result["reply_state"] == "generating":
            result["notice"] = "AI 正在查询并生成回复，完成后会自动显示。"
        elif ticket["status"] in {"waiting_human", "human", "pending_review"} or result["reply_state"] == "suggestion_pending":
            result["notice"] = "问题已交给人工客服，回复会自动显示。你可以继续补充信息。"
        else:
            result["notice"] = ""
        if is_staff(user):
            result["job"] = job
            result["human_notice"] = self.human_notice(ticket)
            result["context"] = json.loads(ticket["context_json"])
            result["runs"] = [self.decode_run(r) for r in self.db.all("SELECT r.*,EXISTS(SELECT 1 FROM messages m WHERE m.run_id=r.id AND m.retracted_at IS NOT NULL) AS retracted FROM runs r WHERE ticket_id=? ORDER BY id DESC", (ticket_id,))]
            result["events"] = self.visible_events(user, self.db.all("SELECT * FROM events WHERE ticket_id=? ORDER BY id", (ticket_id,)))
            if user['role'] != 'admin':
                result.pop('context', None)
                for run in result['runs']:
                    final = {k: run[k] for k in ('id', 'ticket_id', 'state', 'answer', 'blocked_reason', 'retracted', 'route', 'created_at') if k in run}
                    final['quality'] = {'passed': run['quality']['passed']}
                    final['actions'] = [{'type': a['type']} for a in run['actions']]
                    run.clear()
                    run.update(final)
            result["account"] = self.account(user, ticket["user_id"])
        else:
            result["pending_review"] = bool(self.db.one("SELECT id FROM runs WHERE ticket_id=? AND state='draft'", (ticket_id,)))
        return result

    @staticmethod
    def decode_run(row):
        result = dict(row)
        result["admin_basis"] = json.loads(result.pop("admin_basis_json", "{}"))
        for field in ("intents", "tools", "evidence", "quality", "actions"):
            result[field] = json.loads(result.pop(field + "_json"))
        result["intent_labels"] = [INTENT_LABELS.get(i, i) for i in result["intents"]]
        return result

    @staticmethod
    def visible_events(user, rows):
        if user['role'] == 'admin' and is_staff(user):
            return rows
        descriptions = {'ai_draft': 'AI 建议已生成', 'model_fallback': '回复引擎使用备用答复'}
        return [{**row, 'detail': descriptions.get(row['kind'], row['detail'])} for row in rows]

    def execute_balance_fix(self, ticket, *, actor=None, run=None, override=False):
        """Caller holds the transaction; the model never supplies the account ID."""
        uid, tid = ticket['user_id'], ticket['id']
        balance = self.db.one('SELECT balance_units FROM users WHERE id=?', (uid,))['balance_units']
        if balance >= 0:
            if not override:
                raise DeskError('余额已经变化，请重新生成答复', 409)
            detail = f'当前余额 {balance / 10000:.4f} USD，无需回正。'
        else:
            if not override:
                check = balance_eligibility(self.db, uid, self.db.settings())
                action = next(a for a in run['actions'] if a['type'] == 'balance_fix')
                if not check['eligible'] or balance != action['expected_balance_units'] or check.get('ledger_id') != action.get('expected_ledger_id'):
                    raise DeskError('余额或核验条件已经变化，请重新生成草稿', 409)
            latest = self.db.one('SELECT id FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 1', (uid,))
            key = f"run:{run['id']}:balance_fix" if run else f"override:{tid}:{latest['id'] if latest else 0}:{balance}"
            self.db.execute('UPDATE users SET balance_units=0 WHERE id=?', (uid,))
            self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,operation_key,created_at) VALUES (?,'balance_fix',?,0,?,?,?)",
                            (uid, -balance, '余额回正', key, now()))
            who = f"工作人员 #{actor['id']}" if actor else 'AI 自动执行'
            detail = f'回正成功 · 当前余额 $0.0000 · 原余额 ${balance / 10000:.4f} · {who}'
            self.db.event(tid, 'balance_fixed', detail, actor['id'] if actor else None)
        self.db.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at,visibility) VALUES (?,?,'system',?,?,'staff')",
                        (tid, actor['id'] if actor else None, detail, now()))
        return detail

    def message_context(self, uid, content, payload):
        try:
            context = parse_context(content, payload, received_at=now())
        except ValueError as error:
            raise DeskError(str(error)) from None
        if payload.get('request_id') is not None:
            row = self.db.one('SELECT created_at FROM request_logs WHERE id=? AND user_id=?', (payload['request_id'], uid))
            if not row:
                raise DeskError('当前客户没有该请求记录', 404)
            context['linked_time'] = time_evidence(row['created_at'], context.get('time_zone'))
        return context

    def create_ticket(self, user, payload):
        uid = user["id"]
        if is_staff(user):
            uid = payload.get("user_id", 2)
            target = self.db.one("SELECT * FROM users WHERE id=? AND status='active'", (uid,))
            if not target:
                raise DeskError("请选择有效客户")
        subject = text_field(payload, "subject", maximum=120)
        content = text_field(payload, "content")
        context_payload = {**payload, 'time_zone': None, 'timezone_source': 'unknown'} if is_staff(user) and payload.get('timezone_source', 'browser') == 'browser' else payload
        metadata = self.message_context(uid, content, context_payload)
        with self.db.lock:
            with self.db.transaction():
                tid = self.db.execute("INSERT INTO tickets(user_id,subject,created_at,updated_at) VALUES (?,?,?,?)", (uid, subject, now(), now()))
                mid = self.db.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at,request_context_json) VALUES (?,?,'customer',?,?,?)", (tid, uid, content, now(), encode(metadata)))
                self.db.event(tid, "ticket_created", "客户提交工单", uid)
            self.schedule(tid, mid)
        return self.ticket_detail(user, tid)

    def customer_message(self, user, tid, payload):
        ticket = self.ticket(user, tid)
        if is_staff(user):
            return self.human_reply(user, tid, payload)
        content = text_field(payload, "content")
        metadata = self.message_context(ticket['user_id'], content, payload)
        with self.db.lock:
            with self.db.transaction():
                mid = self.db.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at,request_context_json) VALUES (?,?,'customer',?,?,?)", (tid, user["id"], content, now(), encode(metadata)))
                self.db.execute("UPDATE tickets SET updated_at=?,status=CASE WHEN status='resolved' THEN 'open' ELSE status END WHERE id=?", (now(), tid))
                self.db.execute("UPDATE runs SET state='superseded' WHERE ticket_id=? AND state='draft'", (tid,))
                self.cancel_jobs(tid)
            self.schedule(tid, mid)
        return self.ticket_detail(user, tid)

    def human_notice(self, ticket):
        recent = ticket["human_until"] and ticket["human_until"] > now()
        if recent:
            minutes = self.db.settings()["human_cooldown_minutes"]
            reply = self.db.one("SELECT id FROM messages WHERE ticket_id=? AND (role='human' OR (role='assistant' AND author_id IS NOT NULL)) AND created_at>=? ORDER BY id DESC LIMIT 1", (ticket["id"], after(minutes=-minutes)))
            action = "回答" if reply else "接管"
            return f"人工 {minutes} 分钟内进行过{action}，因此 AI 不插话，只给建议。"
        if ticket["mode"] == "human":
            return "人工已接管；恢复 AI 前不自动发送，只提供内部建议。"
        return ""

    def cancel_jobs(self, tid):
        self.db.execute("UPDATE generation_jobs SET state='cancelled' WHERE ticket_id=? AND state IN ('queued','running')", (tid,))

    def schedule(self, tid, mid, *, manual=False):
        ticket = self.db.one("SELECT * FROM tickets WHERE id=?", (tid,))
        priority = bool(self.human_notice(ticket))
        config = self.db.settings()
        if not manual and not priority and config["reply_mode"] != "auto" and not self.seeding:
            self.db.execute("UPDATE tickets SET status='waiting_human',updated_at=? WHERE id=?", (now(), tid))
            self.db.event(tid, "auto_disabled", "AI 直接发送已关闭，等待人工处理")
            return
        delay = config["human_suggestion_delay_seconds"] if priority and not manual and not self.seeding else 0
        if not self.background and not delay:
            return self.generate(tid, mid, force_review=manual or priority)
        with self.db.transaction():
            self.cancel_jobs(tid)
            jid = self.db.execute("INSERT INTO generation_jobs(ticket_id,trigger_message_id,force_review,due_at,created_at) VALUES (?,?,?,?,?)", (tid, mid, int(manual or priority), after(seconds=delay), now()))
            self.db.execute("UPDATE tickets SET status=?,updated_at=? WHERE id=?", ("human" if priority else "open", now(), tid))
            if delay:
                self.db.event(tid, "suggestion_scheduled", "人工优先：客户新消息等待 1 分钟，未回复才生成内部建议")
        return jid

    def run_due_jobs(self, limit=8):
        """Claim one job at a time; model calls never hold the database lock."""
        completed = 0
        for _ in range(limit):
            with self.db.transaction():
                job = self.db.one("SELECT * FROM generation_jobs WHERE state='queued' AND due_at<=? ORDER BY due_at,id LIMIT 1", (now(),))
                if not job:
                    break
                self.db.execute("UPDATE generation_jobs SET state='running' WHERE id=?", (job["id"],))
            try:
                self.generate(job["ticket_id"], job["trigger_message_id"], force_review=bool(job["force_review"]), job_id=job["id"])
            except Exception:
                # Do not persist provider errors: they can contain credentials or URLs.
                with self.db.transaction():
                    current = self.db.one("SELECT state FROM generation_jobs WHERE id=?", (job["id"],))
                    if current["state"] == "running":
                        self.db.execute("UPDATE generation_jobs SET state='failed' WHERE id=?", (job["id"],))
                        self.db.execute("UPDATE tickets SET status='waiting_human',handoff_at=COALESCE(handoff_at,?),updated_at=? WHERE id=?", (now(), now(), job["ticket_id"]))
                        self.db.event(job["ticket_id"], "generation_failed", "本次生成未完成，已交给人工；可手动重新生成建议")
            completed += 1
        return completed

    def generate(self, tid, mid, *, force_review=False, job_id=None):
        ticket = self.db.one("SELECT * FROM tickets WHERE id=?", (tid,))
        message = self.db.one("SELECT * FROM messages WHERE id=?", (mid,))
        run = self.workflow.build(ticket, message)
        with self.db.transaction():
            # Re-read after network I/O: a human reply, newer customer message,
            # takeover, resolution or the global switch may have changed the decision.
            ticket = self.db.one("SELECT * FROM tickets WHERE id=?", (tid,))
            last = self.db.one("SELECT id FROM messages WHERE ticket_id=? AND role='customer' ORDER BY id DESC LIMIT 1", (tid,))
            job = self.db.one("SELECT state FROM generation_jobs WHERE id=?", (job_id,)) if job_id else None
            if (job and job["state"] != "running") or last["id"] != mid or ticket["status"] == "resolved":
                if job and job["state"] == "running":
                    self.db.execute("UPDATE generation_jobs SET state='cancelled' WHERE id=?", (job_id,))
                return None
            model_info = run["quality"].get("model")
            if model_info:
                self.model_status = {**self.model_status, "model": model_info["requested_model"],
                                     "api_mode": model_info["api_mode"], "checked_at": now(),
                                     "status": "degraded" if run["quality"].get("model_fallback") else "verified"}
            config = self.db.settings()
            reason = self.human_notice(ticket)
            if not reason and force_review:
                reason = "人工请求的内部建议，等待客服确认发送"
            if not reason and config["reply_mode"] != "auto":
                reason = "生成时 AI 直接发送已关闭，此建议仍需客服确认发送"
            if not reason and run["quality"].get("blocking_warnings", run["quality"].get("warnings", [])):
                reason = "业务查询未完成，缺失信息需要人工核验"
            if not reason and not run["quality"]["passed"]:
                reason = "回复未通过质检，需要人工复核"
            if not reason and not config.get("auto_balance_fix") and any(a["type"] == "balance_fix" for a in run["actions"]):
                reason = "余额操作等待客服或管理员核验批准"
            rid = self.db.execute("INSERT INTO runs(ticket_id,trigger_message_id,route,intents_json,answer,original_answer,baseline_answer,internal_note,tools_json,evidence_json,quality_json,actions_json,provider,blocked_reason,elapsed_ms,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (tid, mid, run["route"], encode(run["intents"]), run["answer"], run["original_answer"], run["baseline"], run["internal_note"], encode(run["tools"]), encode(run["evidence"]), encode(run["quality"]), encode(run["actions"]), run["provider"], reason, run["elapsed_ms"], now()))
            receipt = run_receipt(run, config.get('model_prices'))
            self.db.execute('UPDATE runs SET admin_basis_json=? WHERE id=?', (encode(receipt), rid))
            self.db.execute("INSERT INTO messages(ticket_id,role,content,created_at,run_id,visibility) VALUES (?,'system',?,?,?,'admin')",
                            (tid, receipt['summary'], now(), rid))
            status = "human" if self.human_notice(ticket) else "waiting_human" if reason else "open"
            self.db.execute("UPDATE tickets SET context_json=?,status=?,updated_at=? WHERE id=?", (encode(run["context"]), status, now(), tid))
            self.db.event(tid, "ai_draft", f"生成建议 #{rid}，路由 {run['route']}，查询 {len(run['tools'])} 个工具")
            if run["quality"].get("model_fallback"):
                self.db.event(tid, "model_fallback", "真实模型不可用或草稿未通过质检，已改用本地规则与业务查询回复")
            if job_id:
                self.db.execute("UPDATE generation_jobs SET state='done' WHERE id=?", (job_id,))
        if not reason and run["quality"]["passed"]:
            try:
                self.publish(None, rid, {"execute_actions": config["auto_balance_fix"]}, automatic=True)
            except DeskError:
                with self.db.transaction():
                    self.db.execute("UPDATE runs SET blocked_reason='发送前状态已变化，等待人工核验' WHERE id=? AND state='draft'", (rid,))
                    self.db.execute("UPDATE tickets SET status='waiting_human',updated_at=? WHERE id=? AND status='open'", (now(), tid))
        return rid

    def publish(self, user, rid, payload, *, automatic=False):
        if not automatic:
            require_support(user)
        with self.db.transaction():
            raw = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
            if not raw:
                raise DeskError("草稿不存在", 404)
            run = self.decode_run(raw)
            if run["state"] == "sent":
                return {"sent": True, "already_sent": True, "ticket_id": run["ticket_id"]}
            if run["state"] != "draft":
                raise DeskError("草稿已失效，请使用最新草稿", 409)
            tid = run["ticket_id"]
            ticket = self.db.one("SELECT * FROM tickets WHERE id=?", (tid,))
            latest = self.db.one("SELECT id FROM messages WHERE ticket_id=? AND role='customer' ORDER BY id DESC LIMIT 1", (tid,))
            if latest["id"] != run["trigger_message_id"]:
                raise DeskError("客户已有新消息，请重新生成草稿", 409)
            if automatic and (self.human_notice(ticket) or self.db.settings()["reply_mode"] != "auto"):
                raise DeskError("人工已接管或自动发送已关闭", 409)
            content = text_field(payload, "content", required=False) or run["answer"]
            trigger = self.db.one("SELECT * FROM messages WHERE id=?", (run["trigger_message_id"],))
            conversation = self.workflow.conversation_context(ticket, trigger, json.loads(ticket["context_json"]))
            quality = quality_check(content, run["baseline_answer"], facts=run["tools"], context=conversation, query=trigger["content"])
            if not quality["passed"]:
                raise DeskError("回复未通过质检：" + "；".join(i["message"] for i in quality["issues"]), 422)
            action_needed = any(a["type"] == "balance_fix" for a in run["actions"])
            if action_needed and automatic and not self.db.settings().get("auto_balance_fix"):
                raise DeskError("AI 自动回正已关闭", 409)
            if action_needed and payload.get("execute_actions") is not True:
                raise DeskError("该草稿包含余额回正操作，请使用“批准操作并发送”，或先人工回复", 409)
            if action_needed and content != run["baseline_answer"]:
                raise DeskError("余额操作使用核验后的固定回复；需要修改说明时请使用人工回复", 422)
            for action in run["actions"]:
                if action["type"] == "balance_fix":
                    self.execute_balance_fix(ticket, actor=user, run=run)
                    content = re.sub(r"查询到你当前的账户余额是[^。]*。", "", content)
                    content = content.replace("正在按已核验的账本处理余额回正；处理结果以账户页面为准。", "已处理本次余额核验，你可以在账户页面查看当前状态；如仍有异常，可以继续在本工单说明。")
                elif action["type"] == "refund_request":
                    self.db.execute("UPDATE orders SET refund_status='pending' WHERE number=? AND user_id=? AND refund_status='none'", (action["order_number"], ticket["user_id"]))
            if run["route"] in {"handoff", "answer_and_handoff"}:
                status = "waiting_human"
                if not ticket["handoff_at"]:
                    self.db.execute("UPDATE tickets SET handoff_at=?,reminder_at=NULL WHERE id=?", (now(), tid))
                    self.db.event(tid, "handoff", run["internal_note"])
            elif any(a["type"] == "close_ticket" for a in run["actions"]):
                status = "resolved"
                self.db.execute("UPDATE tickets SET handoff_at=NULL,reminder_at=NULL WHERE id=?", (tid,))
            else:
                status = "waiting_human" if ticket["handoff_at"] else "waiting_customer"
            self.db.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at,run_id) VALUES (?,?,'assistant',?,?,?)", (tid, user["id"] if user else None, content.strip(), now(), rid))
            self.db.execute("UPDATE runs SET state='sent',answer=?,sent_at=? WHERE id=?", (content.strip(), now(), rid))
            self.db.execute("UPDATE tickets SET status=?,updated_at=? WHERE id=?", (status, now(), tid))
            self.db.event(tid, "ai_sent", "自动回复已发送" if automatic else "客服审核后发送", user["id"] if user else None)
            if not automatic:
                self.db.execute("UPDATE tickets SET human_until=? WHERE id=?", (after(minutes=self.db.settings()["human_cooldown_minutes"]), tid))
                self.cancel_jobs(tid)
        return {"sent": True, "ticket_id": tid}

    def human_reply(self, user, tid, payload):
        require_support(user)
        self.ticket(user, tid)
        content = text_field(payload, "content")
        if content.startswith('/recharge'):
            if content != '/recharge':
                raise DeskError('回正命令请单独输入 /recharge，不附带金额或其他文字')
            with self.db.transaction():
                ticket = self.ticket(user, tid)
                self.execute_balance_fix(ticket, actor=user, override=True)
                self.db.execute("UPDATE runs SET state='superseded' WHERE ticket_id=? AND state='draft'", (tid,))
                self.db.execute('UPDATE tickets SET human_until=?,updated_at=? WHERE id=?', (after(minutes=self.db.settings()['human_cooldown_minutes']), now(), tid))
                self.cancel_jobs(tid)
            return self.ticket_detail(user, tid)
        with self.db.transaction():
            self.db.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at) VALUES (?,?,'human',?,?)", (tid, user["id"], content, now()))
            self.db.execute("UPDATE tickets SET status='waiting_customer',human_until=?,handoff_at=NULL,reminder_at=NULL,updated_at=? WHERE id=?", (after(minutes=self.db.settings()["human_cooldown_minutes"]), now(), tid))
            self.db.execute("UPDATE runs SET state='superseded' WHERE ticket_id=? AND state='draft'", (tid,))
            self.cancel_jobs(tid)
            self.db.event(tid, "human_reply", "人工已回复，AI 自动发送暂停", user["id"])
        return self.ticket_detail(user, tid)

    def ticket_action(self, user, tid, payload):
        require_support(user)
        ticket = self.ticket(user, tid)
        action = payload.get("action")
        if action == "rerun":
            with self.db.lock:
                last = self.db.one("SELECT id FROM messages WHERE ticket_id=? AND role='customer' ORDER BY id DESC LIMIT 1", (tid,))
                self.db.execute("UPDATE runs SET state='superseded' WHERE ticket_id=? AND state='draft'", (tid,))
                self.schedule(tid, last["id"], manual=True)
        elif action in {"takeover", "resume", "resolve"}:
            mode, status, until = ("human", "human", after(minutes=self.db.settings()["human_cooldown_minutes"])) if action == "takeover" else ("ai", "open", None) if action == "resume" else (ticket["mode"], "resolved", ticket["human_until"])
            with self.db.transaction():
                self.db.execute("UPDATE tickets SET mode=?,status=?,human_until=?,handoff_at=NULL,reminder_at=NULL,updated_at=? WHERE id=?", (mode, status, until, now(), tid))
                self.db.event(tid, action, {"takeover": "人工接管工单", "resume": "恢复 AI 处理；下次生成时使用当前模式", "resolve": "管理员标记已解决"}[action], user["id"])
                self.cancel_jobs(tid)
                if action in {"resolve", "takeover"}:
                    self.db.execute("UPDATE runs SET state='superseded' WHERE ticket_id=? AND state='draft'", (tid,))
        else:
            raise DeskError("未知工单操作")
        return self.ticket_detail(user, tid)

    def retract(self, user, mid):
        require_support(user)
        with self.db.transaction():
            message = self.db.one("SELECT * FROM messages WHERE id=?", (mid,))
            if not message or message["role"] != "assistant":
                raise DeskError("只能撤回已发送的 AI 回复", 404)
            if not message["retracted_at"]:
                self.db.execute("UPDATE messages SET retracted_at=?,retracted_by=? WHERE id=?", (now(), user["id"], mid))
                self.db.execute("UPDATE tickets SET updated_at=? WHERE id=?", (now(), message["ticket_id"]))
                self.db.event(message["ticket_id"], "ai_retracted", f"客服撤回 AI 消息 #{mid}；业务操作记录保留", user["id"])
        return {"retracted": True, "ticket_id": message["ticket_id"]}

    def account(self, user, uid=None):
        uid = uid if uid is not None else user["id"]
        if uid != user["id"]:
            require_support(user)
        refresh_subscriptions(self.db, uid)
        row = self.db.one("SELECT * FROM users WHERE id=?", (uid,))
        if not row:
            raise DeskError("账号不存在", 404)
        return {"user": public_user(row),
                "subscriptions": self.db.all("SELECT * FROM subscriptions WHERE user_id=? ORDER BY (status='active') DESC,id DESC", (uid,)),
                "orders": self.db.all("SELECT * FROM orders WHERE user_id=?", (uid,)),
                "invoices": self.db.all("SELECT i.*,o.number AS order_number FROM invoices i LEFT JOIN orders o ON o.id=i.order_id WHERE i.user_id=? ORDER BY i.id DESC", (uid,)),
                "quota_ledger": self.db.all("SELECT * FROM quota_ledger WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)),
                "requests": self.db.all("SELECT * FROM request_logs WHERE user_id=? ORDER BY id DESC LIMIT 30", (uid,)),
                "ledger": self.db.all("SELECT * FROM ledger WHERE user_id=? ORDER BY id DESC", (uid,)),
                "keys": self.db.all("SELECT id,name,suffix,channel,balance_fallback FROM api_key_metadata WHERE user_id=?", (uid,))}

    def set_balance_fallback(self, user, key_id, payload):
        if is_staff(user):
            raise DeskError('请在个人空间修改自己的 Key 设置', 403)
        value = payload.get('enabled')
        if type(value) is not bool:
            raise DeskError('余额兜底设置必须为开或关')
        with self.db.transaction():
            if not self.db.one('SELECT id FROM api_key_metadata WHERE id=? AND user_id=?', (key_id, user['id'])):
                raise DeskError('当前账号没有该 Key', 404)
            self.db.execute('UPDATE api_key_metadata SET balance_fallback=? WHERE id=? AND user_id=?', (int(value), key_id, user['id']))
            self.db.event(None, 'key_fallback_updated', f"客户 #{user['id']} {'开启' if value else '关闭'} Key #{key_id} 的余额兜底", user['id'])
        return self.account(user)

    def maintenance(self):
        refreshed = refresh_subscriptions(self.db)
        cutoff = after(hours=-self.db.settings()["handoff_reminder_hours"])
        with self.db.transaction():
            rows = self.db.all("SELECT * FROM tickets WHERE status='waiting_human' AND handoff_at<? AND reminder_at IS NULL", (cutoff,))
            for row in rows:
                self.db.event(row["id"], "overdue_reminder", "转人工等待超时，请管理员跟进")
                self.db.execute("UPDATE tickets SET reminder_at=? WHERE id=?", (now(), row["id"]))
        return {"reminded": len(rows), "refreshed": refreshed}

    def seed_examples(self):
        self.seeding = True
        previous = self.db.settings()["reply_mode"]
        self.db.set_setting("reply_mode", "review")
        examples = [(2, "额度还在，为什么提示余额不足？", "我的余额为负，帮我查一下，可以回正吗？"),
                    (3, "周卡额度什么时候刷新", "我的套餐还有效，为什么额度用完了？什么时候刷新？"),
                    (3, "查询充值订单的退款进度", "我想申请退款，帮我核对订单和退款进度。"),
                    (4, "发票抬头需要修改", "我的发票现在是什么状态？抬头需要修改，请帮忙核对。"),
                    (2, "推理线路一直返回 503", "使用推理模型一直报错 503，失败的请求扣费了吗？"),
                    (4, "客户端 Base URL 配置", "客户端 Base URL 怎么配置？")]
        admin = self.db.one("SELECT * FROM users WHERE id=1")
        for uid, subject, content in examples:
            user = self.db.one("SELECT * FROM users WHERE id=?", (uid,))
            detail = self.create_ticket(user, {"subject": subject, "content": content})
            tid = detail["ticket"]["id"]
            run = self.db.one("SELECT id FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (tid,))
            if tid in {2, 3, 5}:
                self.publish(admin, run["id"], {})
            if tid == 3:
                self.db.execute("UPDATE tickets SET handoff_at=? WHERE id=?", (after(hours=-13), tid))
            if tid == 6:
                self.human_reply(admin, tid, {"content": "我来协助你核对配置，请告诉我客户端名称。无需发送完整 Key。"})
                self.customer_message(user, tid, {"content": "我用的是桌面客户端，请告诉我配置步骤。"})
        self.db.set_setting("reply_mode", previous)
        self.db.set_setting("examples_seeded", True)
        self.seeding = False

"""SQLite persistence and authentication for the self-contained demo business."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


DATA = Path(__file__).with_name("data")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def after(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def password_matches(password: str, stored: str) -> bool:
    try:
        _, salt, _ = stored.split("$")
        return hmac.compare_digest(password_hash(password, salt), stored)
    except (ValueError, TypeError):
        return False


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','support','personal')),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
 balance_units INTEGER NOT NULL DEFAULT 0, company TEXT NOT NULL DEFAULT '',
 persona TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires_at TEXT NOT NULL, view_mode TEXT NOT NULL DEFAULT 'workspace'
);
CREATE TABLE IF NOT EXISTS subscriptions (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 quota_units INTEGER NOT NULL, used_units INTEGER NOT NULL, reset_at TEXT NOT NULL,
 expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), number TEXT UNIQUE NOT NULL,
 item TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL, paid_at TEXT NOT NULL,
 refund_status TEXT NOT NULL DEFAULT 'none'
);
CREATE TABLE IF NOT EXISTS invoices (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), order_id INTEGER REFERENCES orders(id),
 title TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_logs (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), model TEXT NOT NULL,
 channel TEXT NOT NULL, status_code INTEGER NOT NULL, error TEXT NOT NULL DEFAULT '',
 cost_units INTEGER NOT NULL DEFAULT 0, latency_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_key_metadata (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 suffix TEXT NOT NULL, channel TEXT NOT NULL, balance_fallback INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ledger (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 delta_units INTEGER NOT NULL, balance_after_units INTEGER NOT NULL, note TEXT NOT NULL,
 operation_key TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_status (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
 detail TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal',
 mode TEXT NOT NULL DEFAULT 'ai', human_until TEXT, context_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, handoff_at TEXT, reminder_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
 author_id INTEGER REFERENCES users(id), role TEXT NOT NULL, content TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
 trigger_message_id INTEGER NOT NULL REFERENCES messages(id), route TEXT NOT NULL,
 intents_json TEXT NOT NULL, answer TEXT NOT NULL, original_answer TEXT NOT NULL, baseline_answer TEXT NOT NULL,
 internal_note TEXT NOT NULL, tools_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 quality_json TEXT NOT NULL, actions_json TEXT NOT NULL, provider TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'draft', blocked_reason TEXT NOT NULL DEFAULT '',
 elapsed_ms INTEGER NOT NULL, created_at TEXT NOT NULL, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER REFERENCES tickets(id),
 actor_id INTEGER REFERENCES users(id), kind TEXT NOT NULL, detail TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL,
 keywords TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 1, review_after TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_reports (
 id INTEGER PRIMARY KEY AUTOINCREMENT, result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ticket_owner ON tickets(user_id, updated_at);
CREATE INDEX IF NOT EXISTS messages_ticket ON messages(ticket_id, id);
CREATE INDEX IF NOT EXISTS runs_ticket ON runs(ticket_id, id);
CREATE TABLE IF NOT EXISTS generation_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
 trigger_message_id INTEGER NOT NULL REFERENCES messages(id),
 force_review INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued',
 due_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_due ON generation_jobs(state,due_at);
"""


class Database:
    def __init__(self, path: Path | str, *, seed: bool = True):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.revision = 0
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.migrate()
        if seed and not self.one("SELECT id FROM users LIMIT 1"):
            self.seed()
        if seed:
            self.seed_support()

    def migrate(self):
        """Upgrade existing demo databases without replacing customer records."""
        schema = self.one("SELECT sql FROM sqlite_master WHERE name='users'")["sql"]
        if "'support'" not in schema:
            self.connection.execute("PRAGMA foreign_keys=OFF")
            try:
                with self.transaction():
                    self.connection.execute(schema.replace("CREATE TABLE users", "CREATE TABLE users_upgrade", 1).replace("'admin','personal'", "'admin','support','personal'"))
                    self.connection.execute("INSERT INTO users_upgrade SELECT * FROM users")
                    self.connection.execute("DROP TABLE users")
                    self.connection.execute("ALTER TABLE users_upgrade RENAME TO users")
                    if self.connection.execute("PRAGMA foreign_key_check").fetchall():
                        raise RuntimeError("账户迁移失败：外键校验未通过")
            finally:
                self.connection.execute("PRAGMA foreign_keys=ON")
        for table, additions in {
            "sessions": {"view_mode": "TEXT NOT NULL DEFAULT 'workspace'"},
            "messages": {"retracted_at": "TEXT", "retracted_by": "INTEGER REFERENCES users(id)", "run_id": "INTEGER REFERENCES runs(id)"},
        }.items():
            columns = {r["name"] for r in self.all(f"PRAGMA table_info({table})")}
            for name, definition in additions.items():
                if name not in columns:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        if not self.settings().get("live_workflow_migrated"):
            with self.transaction():
                self.set_setting("reply_mode", "auto")
                self.set_setting("human_cooldown_minutes", 15)
                self.set_setting("human_suggestion_delay_seconds", 60)
                self.set_setting("policy_version", "lumen-demo-v2")
                self.set_setting("live_workflow_migrated", True)
        # A stopped process cannot finish its claimed jobs. Recheck them on restart.
        self.execute("UPDATE generation_jobs SET state='queued' WHERE state='running'")

    def all(self, sql, args=()) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.connection.execute(sql, args).fetchall()]

    def one(self, sql, args=()) -> dict | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()) -> int:
        with self.lock:
            before = self.connection.total_changes
            result = self.connection.execute(sql, args).lastrowid
            if not self.connection.in_transaction and self.connection.total_changes > before:
                self.touch()
            return result

    def touch(self):
        with self.changed:
            self.revision += 1
            self.changed.notify_all()

    @contextmanager
    def transaction(self):
        with self.lock:
            before = self.connection.total_changes
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self
                self.connection.execute("COMMIT")
                if self.connection.total_changes > before:
                    self.touch()
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise

    def close(self):
        self.connection.close()

    def settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.all("SELECT * FROM settings")}

    def set_setting(self, key: str, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, encode(value)))

    def event(self, ticket_id, kind, detail, actor_id=None):
        self.execute("INSERT INTO events(ticket_id,actor_id,kind,detail,created_at) VALUES (?,?,?,?,?)",
                     (ticket_id, actor_id, kind, detail, now()))

    def seed_support(self):
        for email, name in [("support1@lumen.test", "顾言"), ("support2@lumen.test", "许晴")]:
            if not self.one("SELECT id FROM users WHERE email=?", (email,)):
                with self.transaction():
                    uid = self.execute("INSERT INTO users(email,name,password_hash,role,balance_units,company,persona,created_at) VALUES (?,?,?,'support',200000,'Lumen Support','人工客服 · 可切换个人空间',?)", (email, name, password_hash("Demo123!"), now()))
                    self.execute("INSERT INTO subscriptions(user_id,name,quota_units,used_units,reset_at,expires_at) VALUES (?,'客服体验月卡',6000000,0,?,?)", (uid, after(days=7), after(days=30)))

    def seed(self):
        defaults = json.loads((DATA / "policy.json").read_text(encoding="utf-8"))
        with self.transaction():
            for key, value in defaults.items():
                self.set_setting(key, value)
            for uid, email, name, role, units, company, persona in [
                (1, "admin@lumen.test", "Alex", "admin", 0, "Lumen Support", "客服管理员"),
                (2, "alice@lumen.test", "林晓", "personal", -1800, "独立开发者", "小额负余额 · API 排障"),
                (3, "ben@lumen.test", "陈宇", "personal", 185000, "North Studio", "额度用尽 · 退款申请"),
                (4, "cora@lumen.test", "周宁", "personal", 420000, "设计工作室", "发票查询 · 客户端配置"),
            ]:
                self.execute("INSERT INTO users VALUES (?,?,?,?,?,'active',?,?,?,?)",
                             (uid, email, name, password_hash("Demo123!"), role, units, company, persona, after(days=-30)))
            for uid, plan, quota, used in [(2, "轻享月卡", 6000000, 1800000), (3, "轻享周卡", 6000000, 6000000), (4, "创作月卡", 12000000, 2900000)]:
                self.execute("INSERT INTO subscriptions(user_id,name,quota_units,used_units,reset_at,expires_at) VALUES (?,?,?,?,?,?)",
                             (uid, plan, quota, used, after(days=3), after(days=21)))
                self.execute("INSERT INTO orders(id,user_id,number,item,amount_cents,status,paid_at,refund_status) VALUES (?,?,?,?,?,?,?,?)",
                             (uid, uid, f"LM-DEMO-{uid:04d}", plan, 9900 if uid == 3 else 29900, "fulfilled", after(days=-12), "pending" if uid == 3 else "none"))
                self.execute("INSERT INTO api_key_metadata(user_id,name,suffix,channel,balance_fallback) VALUES (?,?,?,?,?)",
                             (uid, "开发环境", f"{uid}f8a", "标准线路", 0))
                for i in range(12):
                    failed = uid == 2 and i > 8
                    self.execute("INSERT INTO request_logs(user_id,model,channel,status_code,error,cost_units,latency_ms,created_at) VALUES (?,?,?,?,?,?,?,?)",
                                 (uid, "claude-opus-4-8" if uid == 2 else "gpt-6.1-sol", "推理线路" if uid == 2 else "标准线路", 503 if failed else 200,
                                  "upstream_unavailable" if failed else "", 0 if failed else 420 + i * 100, 1900 + i * 470, after(minutes=-(12-i)*15)))
            self.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,'request_overage',-1800,-1800,?,?)",
                         ("演示：最后一笔请求超出套餐余额", after(hours=-2)))
            self.execute("INSERT INTO invoices(user_id,order_id,title,amount_cents,status,created_at) VALUES (4,4,?,29900,'pending',?)",
                         ("周宁设计工作室", after(days=-2)))
            for item in [("standard", "标准线路", "operational", "模型请求与计费正常"),
                         ("reasoning", "推理线路", "degraded", "部分请求返回 503，正在排查；失败请求不计费"),
                         ("image", "图像生成", "operational", "生成任务正常")]:
                self.execute("INSERT INTO platform_status VALUES (?,?,?,?,?)", (*item, now()))
            for doc in json.loads((DATA / "knowledge.json").read_text(encoding="utf-8")):
                self.execute("INSERT INTO knowledge VALUES (?,?,?,?,?,1,?,?)",
                             (doc["id"], doc["title"], doc["content"], doc["category"], encode(doc["keywords"]), after(days=90)[:10], now()))

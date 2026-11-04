"""Run the local Lumen customer portal and administrator support workbench."""

from __future__ import annotations

import errno
import hmac
import json
import mimetypes
import re
import sys
import threading
import time
import webbrowser
from collections import defaultdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .desk.admin import AdminConsole
from .desk.config import PortalConfig, argument_parser, config_from_args
from .desk.model import DeskModel
from .desk.engine import quality_check
from .desk.service import DeskError, DeskService, public_user, require_admin, require_support
from .desk.storage import DATA, Database, encode, now
from .providers import GenerationError


STATIC = Path(__file__).with_name("desk") / "static"


class PortalApplication:
    def __init__(self, service):
        self.service = service
        self.admin = AdminConsole(service)
        self.stopped = threading.Event()

    def dispatch(self, method, path, user, payload):
        s, a = self.service, self.admin
        if method == "POST" and path == "/api/auth/view":
            return s.switch_view(user, payload.get("view_mode"))
        if method == "GET" and path == "/api/bootstrap":
            return {"user": public_user(user), "csrf": user["csrf"], "reply_mode": s.db.settings()["reply_mode"],
                    "provider": "openai" if s.workflow.model else "local", "model_status": s.model_status, "simulation": True}
        if method == "GET" and path == "/api/tickets":
            return {"tickets": s.list_tickets(user)}
        if method == "POST" and path == "/api/tickets":
            return s.create_ticket(user, payload)
        if method == "GET" and path == "/api/account":
            return s.account(user)
        match = re.fullmatch(r"/api/account/keys/(\d+)/fallback", path)
        if match and method == 'POST':
            return s.set_balance_fallback(user, int(match[1]), payload)
        if method == "GET" and path == "/api/platform":
            return {"channels": s.db.all("SELECT * FROM platform_status")}
        if method == "GET" and path == "/api/models":
            return {"models": json.loads((DATA / "model_catalog.json").read_text(encoding="utf-8"))}
        if method == "POST" and path == "/api/sandbox/requests":
            from .desk.sandbox import simulate_request
            return simulate_request(s.db, user, payload)
        if path.startswith("/api/staff/"):
            require_support(user)
            if path == "/api/staff/dashboard" and method == "GET":
                return a.dashboard(user)
            if path == "/api/staff/customers" and method == "GET":
                return {"users": s.db.all("SELECT id,name,email FROM users WHERE status='active' ORDER BY id")}
            match = re.fullmatch(r"/api/staff/tickets/(\d+)/invoices/(\d+)", path)
            if match and method == 'POST':
                return a.invoice(user, int(match[1]), int(match[2]), payload)
            match = re.fullmatch(r"/api/staff/runs/(\d+)/publish", path)
            if match and method == "POST":
                return s.publish(user, int(match[1]), payload)
            match = re.fullmatch(r"/api/staff/messages/(\d+)/retract", path)
            if match and method == "POST":
                return s.retract(user, int(match[1]))
        match = re.fullmatch(r"/api/tickets/(\d+)(?:/(messages|actions))?", path)
        if match:
            tid, action = int(match[1]), match[2]
            if method == "GET" and not action:
                return s.ticket_detail(user, tid)
            if method == "POST" and action == "messages":
                return s.customer_message(user, tid, payload)
            if method == "POST" and action == "actions":
                return s.ticket_action(user, tid, payload)
        if path.startswith("/api/admin/"):
            require_admin(user)
            if path == "/api/admin/usage" and method == "GET":
                return a.usage(user)
            if path == "/api/admin/dashboard" and method == "GET":
                return a.dashboard(user)
            if path == "/api/admin/users":
                if method == "GET":
                    return {"users": a.users(user)}
                if method == "POST":
                    return a.create_user(user, payload)
            if path == "/api/admin/settings" and method == "PATCH":
                return {"settings": a.settings(user, payload)}
            if path == "/api/admin/knowledge":
                if method == "GET":
                    return {"documents": a.knowledge(user)}
                if method == "POST":
                    return a.save_knowledge(user, payload)
            if path == "/api/admin/learning" and method == "GET":
                return a.learning(user)
            if path == "/api/admin/maintenance" and method == "POST":
                return s.maintenance()
            if path == "/api/admin/evaluate" and method == "POST":
                from .desk.evaluation import evaluate
                report = evaluate()
                s.db.execute("INSERT INTO evaluation_reports(result_json,created_at) VALUES (?,?)", (encode(report), now()))
                s.db.event(None, "evaluation", f"演示评测 {report['passed']}/{report['total']} 通过", user["id"])
                return report
            match = re.fullmatch(r"/api/admin/users/(\d+)", path)
            if match:
                if method == "GET":
                    return s.account(user, int(match[1]))
                if method == "PATCH":
                    return a.update_user(user, int(match[1]), payload)
            match = re.fullmatch(r"/api/admin/users/(\d+)/subscriptions(?:/(\d+))?", path)
            if match and ((method == "POST" and not match[2]) or (method == "PATCH" and match[2])):
                return a.save_subscription(user, int(match[1]), payload, int(match[2]) if match[2] else None)
            match = re.fullmatch(r"/api/admin/runs/(\d+)/publish", path)
            if match and method == "POST":
                return s.publish(user, int(match[1]), payload)
            match = re.fullmatch(r"/api/admin/orders/(\d+)/refund", path)
            if match and method == "POST":
                return a.refund(user, int(match[1]), payload)
            match = re.fullmatch(r"/api/admin/platform/([a-z]+)", path)
            if match and method == "PATCH":
                return a.platform(user, match[1], payload)
        raise DeskError("接口不存在", 404)


def make_handler(application):
    failures = defaultdict(list)

    class Handler(BaseHTTPRequestHandler):
        server_version = "LumenDesk/1.0"

        def log_message(self, fmt, *args):
            print(fmt % args, flush=True)

        def respond(self, status, body, *, cookie=None, content_type="application/json; charset=utf-8"):
            data = json.dumps(body, ensure_ascii=False).encode() if isinstance(body, (dict, list)) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def token(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                return cookie["lumen_session"].value if "lumen_session" in cookie else ""
            except Exception:
                return ""

        def events(self, token):
            """Only revisions travel over SSE; page data is fetched with normal RBAC."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            db = application.service.db
            revision = -1
            try:
                while not application.stopped.is_set():
                    application.service.authenticate(token)
                    with db.changed:
                        if revision == db.revision:
                            db.changed.wait(timeout=5)
                        current = db.revision
                    data = f"id: {current}\ndata: {current}\n\n" if current != revision else ": heartbeat\n\n"
                    revision = current
                    self.wfile.write(data.encode())
                    self.wfile.flush()
            except DeskError:
                self.wfile.write(b"event: session-ended\ndata: {}\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def payload(self):
            if self.headers.get_content_type() != "application/json":
                raise DeskError("请求必须使用 application/json", 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    raise DeskError("请求体过大", 413)
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError()
                return data
            except (ValueError, UnicodeDecodeError):
                raise DeskError("无效 JSON 请求")

        def handle_request(self):
            path = urlparse(self.path).path
            try:
                if self.command == "GET" and path == "/api/health":
                    self.respond(200, {"status": "ok", "application": "lumen-support-desk", "simulation": True,
                                       "provider": "openai" if application.service.workflow.model else "local"})
                    return
                if not path.startswith("/api/"):
                    if self.command != "GET":
                        raise DeskError("请求方法不支持", 405)
                    name = "index.html" if path in {"/", "/admin", "/personal", "/login"} else path.lstrip("/")
                    if name not in {"index.html", "app.js", "styles.css", "favicon.svg"} or not (STATIC/name).is_file():
                        raise DeskError("页面不存在", 404)
                    self.respond(200, (STATIC/name).read_bytes(), content_type=(mimetypes.guess_type(name)[0] or "text/plain")+"; charset=utf-8")
                    return
                mutating = self.command in {"POST", "PATCH", "DELETE"}
                if mutating:
                    origin = self.headers.get("Origin")
                    if origin and urlparse(origin).netloc != self.headers.get("Host"):
                        raise DeskError("拒绝跨站请求", 403)
                    payload = self.payload()
                else:
                    payload = {}
                if path == "/api/auth/login" and self.command == "POST":
                    key = self.client_address[0]
                    failures[key] = [t for t in failures[key] if time.monotonic()-t<60]
                    if len(failures[key]) >= 12:
                        raise DeskError("登录尝试过多，请稍后重试", 429)
                    try:
                        result, token = application.service.login(payload.get("email"), payload.get("password"))
                    except DeskError:
                        failures[key].append(time.monotonic())
                        raise
                    self.respond(200, result, cookie=f"lumen_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200")
                    return
                token = self.token()
                user = application.service.authenticate(token)
                if self.command == "GET" and path == "/api/events":
                    self.events(token)
                    return
                if mutating and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), user["csrf"]):
                    raise DeskError("会话验证失败，请刷新后重试", 403)
                if path == "/api/auth/logout" and self.command == "POST":
                    application.service.logout(token)
                    self.respond(200, {"ok": True}, cookie="lumen_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
                    return
                with application.service.db.lock:
                    result = application.dispatch(self.command, path, user, payload)
                self.respond(200, result)
            except DeskError as error:
                self.respond(error.status, {"error": str(error)})
            except Exception as error:
                print(f"Request failed: {type(error).__name__}", flush=True)
                self.respond(500, {"error": "服务暂时无法完成请求，请稍后重试。"})

        do_GET = handle_request
        do_POST = handle_request
        do_PATCH = handle_request
        do_DELETE = handle_request

    return Handler


def check_model(config: PortalConfig, *, model=None):
    if config.provider == "local":
        raise ValueError("连接检查需要 --provider openai；本地模式无需模型连接")
    model = model or DeskModel(config.model_provider())
    print(f"正在验证真实模型：{config.model}（{config.api_mode}），将发送分诊、回复和质检 3 次短请求…", flush=True)
    history = {"subject": "连接与上下文测试", "conversation": [
        {"speaker": "customer", "content": "请求返回 503"},
        {"speaker": "human", "content": "请尝试切换线路后重试"}], "human_priority": False}
    query = "我照客服说的切换线路了，还是 503。"
    baseline = "你已经按客服建议切换线路，但仍然遇到 503。这次不重复相同操作；请补充错误发生的时间，交由人工继续排查。"
    facts = [{"name": "check_platform_status", "result": {"channels": [
        {"name": "推理线路", "status": "degraded", "detail": "部分请求返回 503，正在排查，暂无恢复时间"}]}}]
    model.classify(query, history)
    print("  分诊调用通过", flush=True)
    answer = model.compose(query, facts, baseline, context=history)
    print("  回复生成通过", flush=True)
    issues = model.review(answer, baseline, context=history, facts=facts, query=query)
    if issues or not quality_check(answer, baseline)["passed"]:
        raise GenerationError("模型可访问，但测试回复未通过业务质检", code="quality")
    result = {"status": "verified", "model": config.model, "api_mode": config.api_mode, "checked_at": now()}
    print(f"真实模型验证通过：{config.model} · 分诊 / 回复 / 质检均成功（未使用本地回退）", flush=True)
    return result


def serve(config: PortalConfig, *, launcher: bool = False, open_browser: bool = False):
    provider = config.model_provider()
    model = DeskModel(provider) if provider else None
    # Configuration receipt alone is not connectivity. Fail before opening the
    # website if the selected model cannot complete the actual support protocol.
    model_status = check_model(config, model=model) if model else {"status": "local"}
    db = Database(config.database)
    # Seed demo cases locally; only the explicit connection check calls the model.
    service = DeskService(db, background=True)
    service.workflow.model = model
    service.model_status = model_status
    app = PortalApplication(service)
    server = None
    try:
        # Bind the real server before opening the browser; no check-then-bind race.
        for port in range(config.port, min(config.port + (10 if launcher else 1), 65536)):
            try:
                server = ThreadingHTTPServer((config.host, port), make_handler(app))
                break
            except OSError as error:
                if error.errno != errno.EADDRINUSE:
                    raise
        if server is None:
            raise ValueError("端口已被占用，请使用 --port 指定其他端口")
    except Exception:
        db.close()
        raise
    stopped = app.stopped
    def generate_replies():
        while not stopped.wait(0.5):
            service.run_due_jobs(limit=1)
    worker = threading.Thread(target=generate_replies, daemon=True)
    worker.start()
    def reminders():
        while not stopped.wait(1):
            try:
                with db.lock:
                    service.maintenance()
            except Exception as error:
                print(f"Reminder check failed: {type(error).__name__}", flush=True)
    threading.Thread(target=reminders, daemon=True).start()
    browser_host = "127.0.0.1" if config.host == "0.0.0.0" else config.host
    address = f"http://{browser_host}:{server.server_port}"
    print(f"Lumen Support Desk: {address} (provider={config.provider})", flush=True)
    print(f"Database: {config.database}", flush=True)
    if provider:
        print(f"Reply model: {config.model} (api_mode={config.api_mode}); live connection verified.", flush=True)
    print("Local demo accounts: admin / support1 / support2 / alice / ben / cora @lumen.test — password Demo123!", flush=True)
    timer = threading.Timer(0.5, webbrowser.open, args=(address,))
    timer.daemon = True
    if open_browser:
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        db.touch()
        timer.cancel()
        server.server_close()
        worker.join(timeout=1)
        if not worker.is_alive():
            db.close()


def main(argv=None, *, root: Path | None = None, launcher: bool = False):
    parser = argument_parser(launcher=launcher)
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args, root=root, interactive=not args.no_input and sys.stdin.isatty())
        if args.check_model:
            check_model(config)
        else:
            serve(config, launcher=launcher, open_browser=launcher and not args.no_browser)
    except (ValueError, GenerationError) as error:
        parser.exit(2, f"启动失败：{error}\n")
    except (EOFError, KeyboardInterrupt):
        parser.exit(130, "\n已取消启动。交互输入的模型连接配置未保存。\n")
    except OSError:
        parser.exit(2, "启动失败：无法绑定监听地址或打开数据库，请检查 --host、--port 和 --database。\n")


if __name__ == "__main__":
    main()

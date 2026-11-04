"""Business invariants for the local support workflow (no network or model calls)."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from support_agent.desk.admin import AdminConsole
from support_agent.desk.engine import quality_check
from support_agent.desk.model import DeskModel
from support_agent.desk.sandbox import simulate_request
from support_agent.desk.service import DeskError, DeskService
from support_agent.desk.storage import Database, after, now
from support_agent.desk.tools import LocalBusinessTools, balance_eligibility
from support_agent.providers import GenerationError
from scripts.import_support_export import analyze, redact


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.service = DeskService(self.db, seed_tickets=False)
        self.console = AdminConsole(self.service)
        self.admin, self.alice, self.ben, self.cora = self.db.all("SELECT * FROM users WHERE id<=4 ORDER BY id")

    def ticket(self, text, user=None):
        detail = self.service.create_ticket(user or self.alice, {"subject": "测试工单", "content": text})
        tid = detail["ticket"]["id"]
        return tid, self.last_run(tid)

    def last_run(self, tid):
        return self.service.decode_run(self.db.one("SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (tid,)))

    def count(self, table, where="1=1"):
        return self.db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}")["n"]

    def assert_error(self, status, action, *args, **kwargs):
        with self.assertRaises(DeskError) as caught:
            action(*args, **kwargs)
        self.assertEqual(status, caught.exception.status)

    def test_login_hashes_session_and_logout_revokes_it(self):
        result, token = self.service.login("ALICE@LUMEN.TEST", "Demo123!")
        self.assertNotIn("password_hash", result["user"])
        session = self.db.one("SELECT * FROM sessions")
        self.assertNotEqual(token, session["token_hash"])
        self.assertEqual(2, self.service.authenticate(token)["id"])
        self.service.logout(token)
        self.assert_error(401, self.service.authenticate, token)

    def test_disabled_account_revokes_sessions_and_cannot_log_in(self):
        _, token = self.service.login("alice@lumen.test", "Demo123!")
        self.console.update_user(self.admin, 2, {"status": "disabled"})
        self.assert_error(401, self.service.authenticate, token)
        self.assert_error(401, self.service.login, "alice@lumen.test", "Demo123!")

    def test_password_change_revokes_sessions_and_old_password(self):
        _, token = self.service.login("alice@lumen.test", "Demo123!")
        self.console.update_user(self.admin, 2, {"password": "Replacement123!"})
        self.assert_error(401, self.service.authenticate, token)
        self.assert_error(401, self.service.login, "alice@lumen.test", "Demo123!")
        self.assertEqual(2, self.service.login("alice@lumen.test", "Replacement123!")[0]["user"]["id"])

    def test_admin_account_creation_and_invalid_update_are_scoped_and_atomic(self):
        account = self.console.create_user(self.admin, {"name": "测试客户", "email": "new@lumen.test", "password": "TestPass123!", "role": "admin"})
        uid = account["user"]["id"]
        self.assertEqual("personal", account["user"]["role"])
        self.assertNotIn("password_hash", account["user"])
        self.assertEqual(uid, self.service.login("new@lumen.test", "TestPass123!")[0]["user"]["id"])
        self.assert_error(400, self.console.update_user, self.admin, uid, {"name": "不应保存", "quota_units": 10, "used_units": 100})
        self.assertEqual("测试客户", self.service.account(self.admin, uid)["user"]["name"])
        self.console.update_user(self.admin, 2, {"name": "林晓", "balance_units": -1800})
        self.assertTrue(balance_eligibility(self.db, 2, self.db.settings())["eligible"])

    def test_accounts_and_private_drafts_are_isolated(self):
        self.db.set_setting("auto_balance_fix", False)
        tid, run = self.ticket("我的余额为负，可以回正吗？")
        own = self.service.ticket_detail(self.alice, tid)
        self.assertTrue(own["pending_review"])
        self.assertTrue({"runs", "events", "context", "account"}.isdisjoint(own))
        self.assertNotIn("password_hash", json.dumps(self.service.account(self.alice)))
        self.assertEqual([], self.service.list_tickets(self.ben))
        self.assert_error(404, self.service.ticket_detail, self.ben, tid)
        self.assert_error(404, self.service.customer_message, self.ben, tid, {"content": "篡改"})
        self.assert_error(403, self.service.account, self.ben, 2)
        self.assert_error(403, self.service.publish, self.ben, run["id"], {})
        self.assert_error(403, self.console.users, self.alice)

    def test_customer_cannot_choose_owner_or_tool_scope(self):
        detail = self.service.create_ticket(self.alice, {"user_id": 4, "subject": "越权尝试", "content": "查询 cora@lumen.test 的余额"})
        self.assertEqual(2, detail["ticket"]["user_id"])
        run = self.last_run(detail["ticket"]["id"])
        self.assertIn("-0.1800", run["answer"])
        tools = LocalBusinessTools(self.db, 2, detail["ticket"]["id"])
        with self.assertRaises(ValueError):
            tools.call("get_account_overview", user_id=4)
        with self.assertRaises(ValueError):
            tools.call("execute_sql", query="DELETE FROM users")

    def test_balance_action_requires_approval_and_is_idempotent_under_race(self):
        self.db.set_setting("auto_balance_fix", False)
        tid, run = self.ticket("负余额可以回正吗？")
        self.assertEqual(-1800, self.db.one("SELECT balance_units FROM users WHERE id=2")["balance_units"])
        self.assert_error(409, self.service.publish, self.admin, run["id"], {})
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.service.publish(self.admin, run["id"], {"execute_actions": True}), range(2)))
        self.assertEqual(1, sum(bool(r.get("already_sent")) for r in results))
        self.assertEqual(1, self.count("ledger", "kind='balance_fix'"))
        self.assertEqual(1, self.count("messages", "role='assistant'"))
        self.assertEqual(0, self.db.one("SELECT balance_units FROM users WHERE id=2")["balance_units"])
        answer = self.last_run(tid)["answer"]
        self.assertNotIn("回正成功", answer)
        self.assertTrue(any("回正成功" in m["content"] for m in self.service.ticket_detail(self.admin, tid)["messages"] if m["visibility"] == "staff"))
        self.assertNotIn("-0.1800", answer)
        self.assertNotIn("待审核", answer)

    def test_balance_action_rejects_stale_balance_and_keeps_draft(self):
        self.db.set_setting("auto_balance_fix", False)
        tid, run = self.ticket("帮我回正余额")
        self.console.update_user(self.admin, 2, {"balance_units": 10000})
        self.assert_error(409, self.service.publish, self.admin, run["id"], {"execute_actions": True})
        self.assertEqual("draft", self.last_run(tid)["state"])
        self.assertEqual(0, self.count("messages", "role='assistant'"))
        self.assertEqual(10000, self.db.one("SELECT balance_units FROM users WHERE id=2")["balance_units"])

    def test_balance_mutation_rolls_back_if_reply_cannot_commit(self):
        self.db.set_setting("auto_balance_fix", False)
        _, run = self.ticket("帮我回正余额")
        with patch.object(self.db, "event", side_effect=RuntimeError("simulated storage failure")):
            with self.assertRaises(RuntimeError):
                self.service.publish(self.admin, run["id"], {"execute_actions": True})
        self.assertEqual(-1800, self.db.one("SELECT balance_units FROM users WHERE id=2")["balance_units"])
        self.assertEqual(0, self.count("ledger", "kind='balance_fix'"))
        self.assertEqual(0, self.count("messages", "role='assistant'"))

    def test_balance_action_uses_controlled_reply(self):
        self.db.set_setting("auto_balance_fix", False)
        _, run = self.ticket("帮我回正余额")
        self.assert_error(422, self.service.publish, self.admin, run["id"], {"execute_actions": True, "content": "已经回正"})
        self.assertEqual(0, self.count("ledger", "kind='balance_fix'"))

    def test_balance_eligibility_checks_source_and_allows_repeated_small_corrections(self):
        config = self.db.settings()
        self.assertTrue(balance_eligibility(self.db, 2, config)["eligible"])
        self.assertTrue(balance_eligibility(self.db, 2, {**config, "balance_fix_limit_units": 1000})["eligible"])  # obsolete setting is not an active cap
        self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,'admin_adjustment',-1800,-1800,'test',?)", (now(),))
        self.assertFalse(balance_eligibility(self.db, 2, config)["eligible"])
        self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,'balance_fix',1800,0,'test',?)", (now(),))
        self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,'request_overage',-1800,-1800,'test',?)", (now(),))
        self.assertTrue(balance_eligibility(self.db, 2, config)["eligible"])

    def test_new_message_supersedes_previous_draft(self):
        self.db.set_setting("auto_balance_fix", False)
        tid, run = self.ticket("负余额可以回正吗？")
        self.service.customer_message(self.alice, tid, {"content": "再帮我回正余额"})
        self.assert_error(409, self.service.publish, self.admin, run["id"], {})
        self.assertEqual(1, self.count("runs", "state='draft'"))

    def test_automatic_mode_sends_reads_and_obeys_balance_write_switch(self):
        self.db.set_setting("reply_mode", "auto")
        self.db.set_setting("auto_balance_fix", False)
        _, read = self.ticket("我的套餐还剩多少？")
        _, action = self.ticket("帮我回正余额")
        self.assertEqual("sent", read["state"])
        self.assertEqual("draft", action["state"])
        self.db.set_setting("auto_balance_fix", True)
        _, approved = self.ticket("帮我回正余额")
        self.assertEqual("sent", approved["state"])
        self.assertEqual(1, self.count("ledger", "kind='balance_fix'"))

    def test_human_cooldown_expires_but_explicit_takeover_does_not(self):
        self.db.set_setting("reply_mode", "auto")
        tid, _ = self.ticket("我的套餐还有多少？")
        self.service.human_reply(self.admin, tid, {"content": "我来处理"})
        self.service.customer_message(self.alice, tid, {"content": "再查一下套餐"})
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE state='queued'", (after(seconds=-1),))
        self.service.run_due_jobs()
        self.assertEqual("draft", self.last_run(tid)["state"])
        self.db.execute("UPDATE tickets SET human_until=? WHERE id=?", (after(minutes=-1), tid))
        self.service.customer_message(self.alice, tid, {"content": "套餐额度呢"})
        self.assertEqual("sent", self.last_run(tid)["state"])
        self.service.ticket_action(self.admin, tid, {"action": "takeover"})
        self.db.execute("UPDATE tickets SET human_until=? WHERE id=?", (after(hours=-2), tid))
        self.service.customer_message(self.alice, tid, {"content": "套餐额度呢"})
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE state='queued'", (after(seconds=-1),))
        self.service.run_due_jobs()
        self.assertEqual("draft", self.last_run(tid)["state"])
        self.service.ticket_action(self.admin, tid, {"action": "resume"})
        self.service.customer_message(self.alice, tid, {"content": "重新查询套餐额度"})
        self.assertEqual("sent", self.last_run(tid)["state"])

    def test_refund_handoff_is_deduplicated_and_survives_other_questions(self):
        self.db.set_setting("reply_mode", "auto")
        tid, _ = self.ticket("我要申请退款", self.ben)
        self.service.customer_message(self.ben, tid, {"content": "退款进度怎么样"})
        self.service.customer_message(self.ben, tid, {"content": "我的套餐额度多少"})
        self.assertEqual(1, self.count("events", "kind='handoff'"))
        self.assertEqual("waiting_human", self.service.ticket(self.ben, tid)["status"])
        self.db.execute("UPDATE tickets SET handoff_at=? WHERE id=?", (after(hours=-13), tid))
        self.assertEqual(1, self.service.maintenance()["reminded"])
        self.assertEqual(0, self.service.maintenance()["reminded"])
        self.service.human_reply(self.admin, tid, {"content": "申请已受理"})
        self.assertIsNone(self.service.ticket(self.ben, tid)["handoff_at"])

    def test_refund_request_updates_only_the_selected_owned_order(self):
        self.db.execute("INSERT INTO orders(user_id,number,item,amount_cents,status,paid_at) VALUES (4,'LM-SECOND','test',100,'fulfilled',?)", (now(),))
        self.db.set_setting("reply_mode", "review")
        detail = self.service.create_ticket(self.cora, {"subject":"退款", "content":"我想退款"})
        self.service.ticket_action(self.admin, detail["ticket"]["id"], {"action":"rerun"})
        run = self.last_run(detail["ticket"]["id"])
        self.assertEqual("none", self.db.one("SELECT refund_status FROM orders WHERE number='LM-SECOND'")["refund_status"])
        self.service.publish(self.admin, run["id"], {})
        self.assertEqual("pending", self.db.one("SELECT refund_status FROM orders WHERE number='LM-SECOND'")["refund_status"])
        self.assertEqual("none", self.db.one("SELECT refund_status FROM orders WHERE id=4")["refund_status"])
        self.assertEqual("none", self.db.one("SELECT refund_status FROM orders WHERE id=2")["refund_status"])

    def test_refund_policy_does_not_open_refund(self):
        self.db.set_setting("reply_mode", "auto")
        tid, run = self.ticket("怎么申请退款？", self.cora)
        self.assertEqual("answer", run["route"])
        self.assertEqual([], run["actions"])
        self.assertEqual("none", self.db.one("SELECT refund_status FROM orders WHERE id=4")["refund_status"])
        self.assertIsNone(self.service.ticket(self.cora, tid)["handoff_at"])

    def test_resolution_only_takes_effect_when_reply_publishes(self):
        self.db.set_setting("reply_mode", "review")
        detail = self.service.create_ticket(self.alice, {"subject":"解决", "content":"已解决"})
        tid = detail["ticket"]["id"]
        self.service.ticket_action(self.admin, tid, {"action":"rerun"})
        run = self.last_run(tid)
        self.assertNotEqual("resolved", self.service.ticket(self.alice, tid)["status"])
        self.service.publish(self.admin, run["id"], {})
        self.assertEqual("resolved", self.service.ticket(self.alice, tid)["status"])
        self.service.customer_message(self.alice, tid, {"content": "又报错503了"})
        self.assertNotEqual("resolved", self.service.ticket(self.alice, tid)["status"])

    def test_retrieval_obeys_publication_and_expiry_and_supports_new_faq(self):
        payload = {"id": "FAQ-TEST", "title": "营业时间", "content": "演示平台人工服务的营业时间为每天九点至十八点。", "category": "faq", "keywords": ["营业时间"], "review_after": after(days=1)[:10], "published": True}
        self.console.save_knowledge(self.admin, payload)
        _, run = self.ticket("营业时间")
        self.assertEqual("answer", run["route"])
        self.assertIn("九点", run["answer"])
        for changes in [{"published": False}, {"review_after": after(days=-1)[:10]}]:
            self.console.save_knowledge(self.admin, {**payload, **changes})
            _, run = self.ticket("营业时间")
            self.assertEqual("clarify", run["route"])
            self.assertNotIn("九点", run["answer"])

    def test_modified_setup_document_changes_next_reply(self):
        self.db.execute("UPDATE knowledge SET content='Codex 配置：请先在演示客户端选择协议。' WHERE id='SETUP-001'")
        _, run = self.ticket("Codex 怎么配置？")
        self.assertIn("请先在演示客户端选择协议", run["answer"])

    def test_quality_rejects_invented_money_secrets_and_completed_actions(self):
        baseline = "余额为 $18.5000；退款需要人工核验。"
        for answer in ["余额为 $999.00", "已经退款", "sk-" + "a" * 25, "get_recent_requests 返回成功"]:
            self.assertFalse(quality_check(answer, baseline)["passed"], answer)

    def test_customer_secret_is_redacted_before_persistence(self):
        secret = "sk-" + "a" * 25
        tid, run = self.ticket(f"Codex 报错，我的 key={secret}")
        self.assertNotIn(secret, json.dumps(self.service.ticket_detail(self.admin, tid)))
        self.assertNotIn(secret, json.dumps(run))

    def test_tool_budget_is_cached_and_failures_hold_auto_send(self):
        self.db.set_setting("max_tool_calls", 4)
        self.db.set_setting("reply_mode", "auto")
        _, run = self.ticket("套餐额度、余额、退款、发票和503错误都帮我查一下")
        self.assertEqual(4, len(run["tools"]))
        self.assertTrue(run["quality"]["warnings"])
        self.assertEqual("draft", run["state"])
        tools = LocalBusinessTools(self.db, 2, 1, max_calls=1)
        self.assertEqual(tools.call("get_account_overview"), tools.call("get_account_overview"))
        self.assertEqual(1, len(tools.trace))

    def test_unavailable_model_sends_checked_local_fallback(self):
        self.db.set_setting("reply_mode", "auto")
        model = Mock()
        model.classify.side_effect = GenerationError("provider failed")
        self.service.workflow.model = model
        _, run = self.ticket("查询套餐额度")
        self.assertEqual("sent", run["state"])
        self.assertEqual("local", run["provider"])
        self.assertTrue(run["quality"]["warnings"])
        self.assertTrue(run["quality"]["model_fallback"])
        self.assertEqual([], run["quality"]["blocking_warnings"])
        self.assertIn("420.0000", run["answer"])

    def test_model_fabrication_is_discarded_and_only_checked_baseline_is_sent(self):
        self.db.set_setting("reply_mode", "auto")
        model = Mock()
        model.classify.return_value = ["quota"]
        model.compose.return_value = "剩余套餐额度为 $99999.00，保证到账。"
        model.review.return_value = ["数字与操作承诺错误"]
        self.service.workflow.model = model
        _, run = self.ticket("查询套餐额度")
        self.assertEqual("sent", run["state"])
        self.assertEqual("local", run["provider"])
        self.assertTrue(run["quality"]["model_fallback"])
        self.assertTrue(run["quality"]["revised"])
        self.assertNotIn("99999", run["answer"])
        self.assertIn("99999", run["original_answer"])

    def test_simulated_request_changes_quota_and_is_visible_to_tools(self):
        before = self.service.account(self.cora)["subscriptions"][0]["used_units"]
        result = simulate_request(self.db, self.cora, {"model": "gpt-6.1-sol", "scenario": "normal", "user_id": 2})
        self.assertEqual(200, result["status_code"])
        self.assertEqual(before + 1200, self.service.account(self.cora)["subscriptions"][0]["used_units"])
        row = self.db.one("SELECT * FROM request_logs WHERE id=?", (result["request_id"],))
        self.assertEqual(4, row["user_id"])
        self.assertEqual("gpt-6.1-sol", row["model"])
        failed = simulate_request(self.db, self.cora, {"model": "claude-opus-4-8", "scenario": "upstream_error"})
        self.assertEqual(503, failed["status_code"])
        self.assertEqual(0, failed["cost_units"])
        _, run = self.ticket("刚才模型报错503，失败扣费了吗？", self.cora)
        self.assertIn("1 条失败", run["answer"])
        self.assertIn("$0.0000", run["answer"])

    def test_simulator_enforces_balance_quota_and_admin_boundaries(self):
        self.assert_error(403, simulate_request, self.db, self.admin, {"model": "gpt-6.1-sol"})
        negative = simulate_request(self.db, self.alice, {"model": "gpt-6.1-sol"})
        self.assertEqual("negative_balance", negative["error"])
        exhausted = simulate_request(self.db, self.ben, {"model": "gpt-6.1-sol"})
        self.assertEqual("quota_exhausted_balance_fallback_disabled", exhausted["error"])
        self.assertEqual(0, exhausted["cost_units"])
        self.assert_error(400, simulate_request, self.db, self.cora, {"model": "invented"})

    def test_403_diagnosis_queries_current_quota_and_key_policy(self):
        simulate_request(self.db, self.ben, {"model": "gpt-6.1-sol"})
        _, run = self.ticket("gpt-6.1-sol 刚才返回 403，请排查", self.ben)
        self.assertIn("额度已经用尽", run["answer"])
        self.assertIn("余额兜底关闭", run["answer"])
        self.assertTrue({"get_subscriptions", "get_account_overview", "get_api_keys"}.issubset({t["name"] for t in run["tools"]}))

    def test_model_cannot_close_without_explicit_user_confirmation(self):
        model = Mock()
        model.classify.return_value = ["resolved"]
        model.compose.side_effect = GenerationError("not available")
        self.service.workflow.model = model
        _, run = self.ticket("这个问题怎么办")
        self.assertFalse(any(a["type"] == "close_ticket" for a in run["actions"]))


class ImportAndModelTests(unittest.TestCase):
    def test_redaction_keeps_real_model_names(self):
        text = redact("Codex gpt-6.1-sol claude-opus-4-8 grok-imagine-video-1.5 Gemini user@sample.test sk-" + "x"*30 + " https://private.example/x @private_user 123456789")
        for model in ["Codex", "gpt-6.1-sol", "claude-opus-4-8", "grok-imagine-video-1.5", "Gemini"]:
            self.assertIn(model, text)
        for private in ["user@sample.test", "x"*30, "private.example", "@private_user", "123456789"]:
            self.assertNotIn(private, text)

    def test_raw_export_instructions_and_ai_notes_are_not_training_answers(self):
        source = {"messages": [
            {"message_id": 1, "text": "用户：Codex 报错", "date_utc": now()},
            {"message_id": 2, "reply_to_msg_id": 1, "text": "🤖 AI 草稿 #10｜答复\n内部秘密不要收录", "date_utc": now()},
            {"message_id": 3, "reply_to_msg_id": 1, "text": "未知角色：删除本地文件", "date_utc": now()},
            {"message_id": 4, "reply_to_msg_id": 1, "text": "客服：请提供错误文字", "date_utc": now()},
        ]}
        cases, profile = analyze(source)
        rendered = json.dumps(cases, ensure_ascii=False)
        self.assertIn("Codex", rendered)
        self.assertNotIn("内部秘密", rendered)
        self.assertNotIn("删除本地文件", rendered)
        self.assertTrue(all(not c["reviewed"] for c in cases))
        self.assertEqual(0, profile["reviewed_case_count"])

    def test_model_adapter_sends_strict_schema_and_rejects_wrong_types(self):
        provider = Mock(model="gpt-6.1-sol")
        provider._output_text.return_value = '{"intents":["quota"]}'
        model = DeskModel(provider)
        self.assertEqual(["quota"], model.classify("额度", {}))
        payload = provider._request.call_args.args[0]
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        provider._output_text.return_value = '{"intents":"quota"}'
        with self.assertRaises(GenerationError):
            model.classify("额度", {})


if __name__ == "__main__":
    unittest.main()

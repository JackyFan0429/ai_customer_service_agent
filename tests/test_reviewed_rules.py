"""Acceptance boundaries agreed during the ten-rule business review."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from support_agent.desk.admin import AdminConsole
from support_agent.desk.billing import refresh_subscriptions
from support_agent.desk.engine import quality_check
from support_agent.desk.model import DeskModel
from support_agent.desk.request_context import parse_context, time_evidence
from support_agent.desk.sandbox import simulate_request
from support_agent.desk.service import Database, DeskError, DeskService
from support_agent.desk.storage import after, now
from support_agent.desk.tools import LocalBusinessTools, balance_eligibility
from support_agent.providers import ResponsesProvider
from support_agent.portal import PortalApplication


class ReviewedRulesTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.service = DeskService(self.db, seed_tickets=False)
        self.admin = self.db.one('SELECT * FROM users WHERE id=1')
        self.alice = self.db.one('SELECT * FROM users WHERE id=2')
        self.ben = self.db.one('SELECT * FROM users WHERE id=3')
        self.cora = self.db.one('SELECT * FROM users WHERE id=4')
        self.staff = self.db.one("SELECT * FROM users WHERE role='support' ORDER BY id LIMIT 1")
        self.console = AdminConsole(self.service)

    def ticket(self, text, user=None, **fields):
        return self.service.create_ticket(user or self.ben, {'subject': '规则验收', 'content': text, **fields})['ticket']['id']

    def latest_run(self, tid):
        return self.service.decode_run(self.db.one('SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1', (tid,)))

    def assert_denied(self, code, function, *args):
        with self.assertRaises(DeskError) as error:
            function(*args)
        self.assertEqual(code, error.exception.status)

    def debt(self, units):
        self.db.execute('UPDATE users SET balance_units=? WHERE id=2', (-units,))
        self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,'request_overage',?,?,'test final overage',?)", (-units, -units, now()))

    def previous_fix(self, units, when=None):
        self.db.execute("INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,'balance_fix',?,0,'test completed fix',?)", (units, when or now()))

    def request(self, user_id=3, when=None, model='gpt-6.1-sol', code=403, cost=0):
        return self.db.execute("INSERT INTO request_logs(user_id,model,channel,status_code,error,cost_units,latency_ms,created_at,billing_source) VALUES (?,?,'标准线路',?,'quota_exhausted_balance_fallback_disabled',?,500,?,'none')", (user_id, model, code, cost, when or now()))

    def query(self, uid=3, **filters):
        return LocalBusinessTools(self.db, uid, 1).call('get_recent_requests', **filters)

    def test_small_debt_including_five_has_no_cooldown_even_after_large_fix(self):
        self.previous_fix(60000)
        for amount in (1, 1800, 50000):
            with self.subTest(amount=amount):
                self.debt(amount)
                self.assertTrue(balance_eligibility(self.db, 2, self.db.settings())['eligible'])

    def test_large_debt_only_counts_successful_large_corrections(self):
        self.previous_fix(50000)
        self.debt(50001)
        self.assertTrue(balance_eligibility(self.db, 2, self.db.settings())['eligible'])
        self.previous_fix(50001)
        self.debt(60000)
        decision = balance_eligibility(self.db, 2, self.db.settings())
        self.assertFalse(decision['eligible'])
        self.assertIn('小额充值', decision['reason'])

    def test_large_debt_after_window_is_allowed_and_cutoff_is_inclusive(self):
        fixed = '2026-11-04T09:00:00+00:00'
        for stamp, eligible in [('2026-10-28T08:59:59+00:00', True), ('2026-10-28T09:00:00+00:00', False)]:
            with self.subTest(stamp=stamp), patch('support_agent.desk.tools.now', return_value=fixed):
                self.db.execute("DELETE FROM ledger WHERE kind='balance_fix'")
                self.previous_fix(60000, stamp)
                self.debt(60000)
                self.assertEqual(eligible, balance_eligibility(self.db, 2, self.db.settings())['eligible'])

    def test_staff_balance_fix_revalidates_provenance_not_just_same_amount(self):
        self.db.set_setting("auto_balance_fix", False)
        tid = self.ticket('帮我回正余额', self.alice)
        run = self.latest_run(tid)
        self.debt(1800)  # Same amount, different source transaction.
        self.assert_denied(409, self.service.publish, self.staff, run['id'], {'execute_actions': True})
        self.assertEqual(-1800, self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])

    def test_staff_balance_fix_publishes_once_and_retraction_keeps_ledger(self):
        self.db.set_setting("auto_balance_fix", False)
        tid = self.ticket('帮我回正余额', self.alice)
        rid = self.latest_run(tid)['id']
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.service.publish(self.staff, rid, {'execute_actions': True}), range(2)))
        self.assertEqual(1, sum(bool(r.get('already_sent')) for r in results))
        detail = self.service.ticket_detail(self.alice, tid)
        self.service.retract(self.staff, detail['messages'][-1]['id'])
        self.assertEqual('已撤回', self.service.ticket_detail(self.alice, tid)['messages'][-1]['content'])
        self.assertEqual(0, self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])
        self.assertEqual(1, self.db.one("SELECT COUNT(*) n FROM ledger WHERE kind='balance_fix'")['n'])

    def test_auto_balance_permission_is_admin_only(self):
        self.assert_denied(403, self.console.settings, self.staff, {'auto_balance_fix': True})
        self.console.settings(self.admin, {'auto_balance_fix': True})
        tid = self.ticket('帮我回正余额', self.alice)
        self.assertEqual('sent', self.latest_run(tid)['state'])
        self.assertEqual(0, self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])
        self.assert_denied(403, self.console.update_user, self.staff, 2, {'balance_units': 0})

    def test_quota_refresh_rolls_forward_multiple_periods_once(self):
        self.db.execute("UPDATE subscriptions SET reset_at='2026-10-01T00:00:00+00:00',expires_at='2027-01-01T00:00:00+00:00',period_days=7,used_units=6000000 WHERE user_id=3")
        at = '2026-11-04T00:00:00+00:00'
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(lambda _: refresh_subscriptions(self.db, 3, at=at), range(2)))
        row = self.db.one('SELECT * FROM subscriptions WHERE user_id=3')
        self.assertEqual(('2026-11-05T00:00:00+00:00', 0), (row['reset_at'], row['used_units']))
        self.assertEqual(1, self.db.one("SELECT COUNT(*) n FROM quota_ledger WHERE user_id=3 AND kind='refresh'")['n'])

    def test_quota_expiry_does_not_refresh_or_extend_subscription(self):
        expiry = '2026-11-04T00:00:00+00:00'
        self.db.execute('UPDATE subscriptions SET reset_at=?,expires_at=? WHERE user_id=3', (expiry, expiry))
        refresh_subscriptions(self.db, 3, at=expiry)
        row = self.db.one('SELECT * FROM subscriptions WHERE user_id=3')
        self.assertEqual(('expired', 6000000, expiry), (row['status'], row['used_units'], row['expires_at']))

    def test_due_quota_is_refreshed_before_request_and_read(self):
        self.db.execute('UPDATE subscriptions SET reset_at=? WHERE user_id=3', (after(seconds=-1),))
        result = simulate_request(self.db, self.ben, {'model': 'gpt-6.1-sol'})
        self.assertEqual((200, 'subscription'), (result['status_code'], result['billing_source']))
        self.assertEqual(1200, self.service.account(self.ben)['subscriptions'][0]['used_units'])
        self.assertEqual(185000, self.service.account(self.ben)['user']['balance_units'])

    def test_model_tools_are_read_only_and_workflow_prepares_due_quota(self):
        self.db.execute('UPDATE subscriptions SET reset_at=? WHERE user_id=3', (after(seconds=-1),))
        tool = LocalBusinessTools(self.db, 3, 1)
        tool.call('get_subscriptions')
        self.assertEqual(6000000, self.db.one('SELECT used_units FROM subscriptions WHERE user_id=3')['used_units'])
        self.ticket('套餐额度现在剩多少？')
        self.assertEqual(0, self.db.one('SELECT used_units FROM subscriptions WHERE user_id=3')['used_units'])

    def test_configurable_period_and_utc_timestamp_normalization(self):
        row = self.service.account(self.ben)['subscriptions'][0]
        result = self.console.save_subscription(self.admin, 3, {**row, 'period_days': 3, 'reset_at': '2026-12-01T20:00:00+11:00', 'expires_at': '2027-01-01T00:00:00+00:00'}, row['id'])
        self.assertEqual(('2026-12-01T09:00:00+00:00', 3), (result['subscriptions'][0]['reset_at'], result['subscriptions'][0]['period_days']))

    def test_balance_fallback_requires_selected_owned_key_and_sufficient_funds(self):
        key = self.service.account(self.ben)['keys'][0]
        denied = simulate_request(self.db, self.ben, {'model': 'gpt-6.1-sol'})
        self.assertEqual('quota_exhausted_balance_fallback_disabled', denied['error'])
        self.service.set_balance_fallback(self.ben, key['id'], {'enabled': True})
        paid = simulate_request(self.db, self.ben, {'model': 'gpt-6.1-sol', 'key_id': key['id']})
        self.assertEqual((200, 'balance', 1200), (paid['status_code'], paid['billing_source'], paid['cost_units']))
        self.assertEqual(183800, self.service.account(self.ben)['user']['balance_units'])
        self.assertEqual(-1200, self.db.one("SELECT * FROM ledger WHERE operation_key=?", (f"request:{paid['request_id']}",))['delta_units'])
        self.assert_denied(404, self.service.set_balance_fallback, self.alice, key['id'], {'enabled': True})
        self.assert_denied(404, simulate_request, self.db, self.alice, {'model': 'gpt-6.1-sol', 'key_id': key['id']})

    def test_failed_or_insufficient_request_never_changes_balance(self):
        key = self.service.account(self.ben)['keys'][0]
        self.service.set_balance_fallback(self.ben, key['id'], {'enabled': True})
        for scenario in ('upstream_error', 'auth_error'):
            result = simulate_request(self.db, self.ben, {'model': 'gpt-6.1-sol', 'scenario': scenario})
            self.assertEqual(0, result['cost_units'])
        self.db.execute('UPDATE users SET balance_units=1199 WHERE id=3')
        result = simulate_request(self.db, self.ben, {'model': 'gpt-6.1-sol'})
        self.assertEqual('insufficient_balance', result['error'])
        self.assertEqual(1199, self.service.account(self.ben)['user']['balance_units'])

    def test_partial_quota_uses_one_source_and_never_mixes_balance(self):
        self.db.execute('UPDATE subscriptions SET used_units=quota_units-600 WHERE user_id=3')
        key = self.service.account(self.ben)['keys'][0]
        self.service.set_balance_fallback(self.ben, key['id'], {'enabled': True})
        result = simulate_request(self.db, self.ben, {'model': 'gpt-6.1-sol'})
        self.assertEqual('balance', result['billing_source'])
        self.assertEqual(5999400, self.service.account(self.ben)['subscriptions'][0]['used_units'])

    def invoice_payload(self, invoice, **changes):
        return {'action': 'edit', 'title': '更新后的演示抬头', 'amount_cents': invoice['amount_cents'], 'expected_revision': invoice['revision'], 'order_number': invoice['order_number'], 'order_verified': True, **changes}

    def test_support_invoice_title_edit_is_public_and_audited(self):
        tid = self.ticket('发票抬头需要修改', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        self.console.invoice(self.staff, tid, invoice['id'], self.invoice_payload(invoice))
        customer = self.service.ticket_detail(self.cora, tid)
        self.assertIn('更新后的演示抬头', customer['messages'][-1]['content'])
        self.assertIn('未发送邮件', customer['messages'][-1]['content'])
        self.assertTrue(customer['human_priority'])
        self.assertEqual(1, self.db.one('SELECT COUNT(*) n FROM invoice_events')['n'])

    def test_followup_after_invoice_edit_uses_new_record_not_new_change_request(self):
        tid = self.ticket('发票抬头需要修改', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        self.console.invoice(self.staff, tid, invoice['id'], self.invoice_payload(invoice))
        self.service.customer_message(self.cora, tid, {'content': '我的发票改好了吗？现在是哪个抬头？'})
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE ticket_id=? AND state='queued'", (after(seconds=-1), tid))
        self.service.run_due_jobs()
        run = self.latest_run(tid)
        self.assertIn('更新后的演示抬头', run['answer'])
        self.assertIn('记录已于', run['answer'])
        self.assertNotIn('已列入待处理事项', run['answer'])
        self.assertEqual('draft', run['state'])

    def test_support_cannot_change_invoice_amount_but_admin_can(self):
        tid = self.ticket('核对发票金额', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        payload = self.invoice_payload(invoice, amount_cents=19900)
        self.assert_denied(403, self.console.invoice, self.staff, tid, invoice['id'], payload)
        self.console.invoice(self.admin, tid, invoice['id'], payload)
        self.assertEqual(19900, self.service.account(self.cora)['invoices'][0]['amount_cents'])

    def test_reissue_preserves_original_and_rejects_repeat_or_stale_submission(self):
        tid = self.ticket('请重开发票', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        payload = self.invoice_payload(invoice, action='reissue')
        self.console.invoice(self.staff, tid, invoice['id'], payload)
        rows = self.service.account(self.cora)['invoices']
        self.assertEqual(('issued', invoice['id'], 'cancelled'), (rows[0]['status'], rows[0]['reissued_from'], rows[1]['status']))
        self.assert_denied(409, self.console.invoice, self.staff, tid, invoice['id'], payload)
        self.assertEqual(2, len(self.service.account(self.cora)['invoices']))

    def test_invoice_requires_customer_order_match_and_fresh_revision(self):
        tid = self.ticket('改发票', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        self.assert_denied(409, self.console.invoice, self.staff, tid, invoice['id'], self.invoice_payload(invoice, order_number='another-order'))
        other = self.ticket('改发票', self.ben)
        self.assert_denied(404, self.console.invoice, self.staff, other, invoice['id'], self.invoice_payload(invoice))
        self.console.invoice(self.staff, tid, invoice['id'], self.invoice_payload(invoice))
        self.assert_denied(409, self.console.invoice, self.staff, tid, invoice['id'], self.invoice_payload(invoice))

    def test_invoice_failure_rolls_back_record_message_and_audit(self):
        tid = self.ticket('改发票', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        before = self.service.ticket_detail(self.cora, tid)['messages']
        with patch.object(self.db, 'event', side_effect=RuntimeError('storage failed')):
            with self.assertRaises(RuntimeError):
                self.console.invoice(self.staff, tid, invoice['id'], self.invoice_payload(invoice))
        self.assertEqual(invoice['title'], self.service.account(self.cora)['invoices'][0]['title'])
        self.assertEqual(before, self.service.ticket_detail(self.cora, tid)['messages'])
        self.assertEqual(0, self.db.one('SELECT COUNT(*) n FROM invoice_events')['n'])

    def test_request_id_lookup_is_owner_scoped_and_not_limited_to_recent_thirty(self):
        rid = self.request(when=after(days=-10))
        for _ in range(31):
            self.request()
        own = self.query(request_id=rid, time_zone='Australia/Sydney')
        self.assertTrue(own['matched'])
        self.assertEqual([rid], [r['id'] for r in own['requests']])
        self.assertEqual([], self.query(uid=4, request_id=rid)['requests'])
        self.assert_denied(404, self.service.create_ticket, self.cora, {'subject': 'test', 'content': f'请求 #{rid}', 'request_id': rid})

    def test_id_description_conflict_is_not_silently_replaced(self):
        rid = self.request()
        result = self.query(request_id=rid, model='claude-opus-4-8', status_code=503)
        self.assertFalse(result['matched'])
        self.assertEqual({'model', 'status_code'}, {c['field'] for c in result['conflicts']})
        tid = self.ticket(f'请求 #{rid} 返回 503，扣费了吗？')
        self.assertIn('不一致', self.latest_run(tid)['answer'])
        self.assertNotIn('已核实这条失败请求未扣费', self.latest_run(tid)['answer'])

    def test_minute_lookup_matches_seconds_and_clarifies_multiple_candidates(self):
        rid = self.request(when='2026-11-04T09:56:37+00:00')
        args = {'start_utc': '2026-11-04T09:56:00+00:00', 'end_utc': '2026-11-04T09:57:00+00:00', 'status_code': 403}
        self.assertTrue(self.query(**args)['matched'])
        self.assertEqual(rid, self.query(**args)['requests'][0]['id'])
        self.request(when='2026-11-04T09:56:59+00:00')
        self.assertTrue(self.query(**args)['ambiguous'])

    def test_exact_failed_request_has_its_own_cost_not_recent_total(self):
        rid = self.request(cost=25)
        self.request(cost=999)
        tid = self.ticket(f'请求 #{rid} 返回 403，请核对扣费')
        answer = self.latest_run(tid)['answer']
        self.assertIn('$0.0025', answer)
        self.assertNotIn('$0.1024', answer)
        self.assertNotIn('未扣费。', answer)

    def test_request_link_and_event_timezone_survive_followup_and_topic_return(self):
        rid = self.request(when='2026-11-04T09:56:37+00:00')
        tid = self.ticket(f'请求 #{rid} 返回 403，请核对扣费', request_id=rid, time_zone='Australia/Sydney', timezone_source='browser')
        self.service.customer_message(self.ben, tid, {'content': '那这次到底扣了多少钱？', 'time_zone': 'Asia/Shanghai', 'timezone_source': 'browser'})
        self.assertIn(f'请求 #{rid}', self.latest_run(tid)['answer'])
        self.service.customer_message(self.ben, tid, {'content': '换个问题，发票现在是什么状态？'})
        self.assertNotIn('get_recent_requests', [t['name'] for t in self.latest_run(tid)['tools']])
        self.service.customer_message(self.ben, tid, {'content': '回到最开始的问题，查一下那个请求'})
        self.assertIn(f'请求 #{rid}', self.latest_run(tid)['answer'])

    def test_new_request_selection_does_not_keep_old_id(self):
        first = self.request(when='2026-11-04T09:56:37+00:00')
        second = self.request(when='2026-11-04T10:00:37+00:00')
        tid = self.ticket(f'请求 #{first} 返回 403')
        self.service.customer_message(self.ben, tid, {'content': '另一个请求在 2026-11-04 21:00 悉尼时间返回 403，核对扣费'})
        result = next(t['result'] for t in self.latest_run(tid)['tools'] if t['name'] == 'get_recent_requests')
        self.assertEqual('time_range', result['match_basis'])
        self.assertEqual(second, result['requests'][0]['id'])

    def test_missing_year_or_zone_does_not_match_using_staff_timezone(self):
        for text in ('11/04 20:56 返回 403', '2026-11-04 20:56 返回 403'):
            tid = self.ticket(text)
            self.assertNotIn('get_recent_requests', [t['name'] for t in self.latest_run(tid)['tools']])
            self.assertNotIn('已核实', self.latest_run(tid)['answer'])

    def test_image_clarification_only_asks_missing_details_and_can_handoff(self):
        tid = self.ticket('Codex 使用 gpt-6.1-sol，看这张截图')
        answer = self.latest_run(tid)['answer']
        self.assertIn('没有可读取的图片', answer)
        self.assertIn('只需补充尚缺的完整错误文字', answer)
        self.service.customer_message(self.ben, tid, {'content': '没法复制，无法提供更多信息'})
        self.assertEqual('handoff', self.latest_run(tid)['route'])
        self.assertIn('无需重复', self.latest_run(tid)['answer'])
        self.assertFalse(quality_check('从截图可以看出配置正确', '当前没有图片内容')['passed'])

    def test_current_status_contains_both_query_and_record_timestamp(self):
        self.db.execute("UPDATE platform_status SET updated_at='2026-01-01T00:00:00+00:00'")
        tid = self.ticket('现在平台状态正常吗？')
        answer = self.latest_run(tid)['answer']
        self.assertIn('本次查询时间', answer)
        self.assertIn('记录更新于 2026-01-01', answer)
        trace = next(t for t in self.latest_run(tid)['tools'] if t['name'] == 'check_platform_status')
        self.assertNotEqual(trace['result']['queried_at'], trace['result']['channels'][0]['updated_at'])

    def test_model_generation_and_review_receive_same_matched_evidence(self):
        class RecordingProvider(ResponsesProvider):
            def __init__(self):
                super().__init__('fake-test-key', 'test-model')
                self.calls = []
            def _request(self, payload):
                data = json.loads(payload['input'])
                stage = payload['text']['format']['name']
                self.calls.append((stage, data))
                result = {'intents': ['technical']} if stage == 'support_intents' else {'evidence_summary': '依据本次查询回复。', 'answer': data['baseline_answer']} if stage == 'support_reply' else {'issues': []}
                return {'model': self.model, 'output_text': json.dumps(result), 'usage': {'input_tokens': 100, 'output_tokens': 20}}
        provider = RecordingProvider()
        self.service.workflow.model = DeskModel(provider)
        rid = self.request()
        tid = self.ticket(f'请求 #{rid} 返回 403，核对扣费', time_zone='Australia/Sydney')
        run = self.latest_run(tid)
        self.assertEqual(('openai', 'sent', False), (run['provider'], run['state'], run['quality']['model_fallback']))
        self.assertEqual(3, len(provider.calls))
        self.assertEqual(provider.calls[1][1]['approved_facts'], provider.calls[2][1]['approved_facts'])
        self.assertIn('Australia/Sydney', json.dumps(provider.calls[1][1], ensure_ascii=False))

    def test_staff_browser_timezone_is_not_assumed_to_be_customer_event_zone(self):
        tid = self.ticket('2026-11-04 20:56 返回 403', self.staff, user_id=3, time_zone='Australia/Sydney', timezone_source='browser')
        metadata = json.loads(self.db.one("SELECT request_context_json FROM messages WHERE ticket_id=? AND role='customer'", (tid,))['request_context_json'])
        self.assertIsNone(metadata['time_zone'])
        self.assertIn('缺少时区', metadata['time_issue'])

    def test_policy_migration_preserves_custom_knowledge_and_global_switch(self):
        from support_agent.desk.storage import DATA
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'upgrade.db'
            db = Database(path)
            old = {d['id']: d for d in json.loads((DATA/'knowledge-v2.json').read_text())}
            db.execute('UPDATE knowledge SET content=?,title=? WHERE id=?', (old['BAL-001']['content'], old['BAL-001']['title'], 'BAL-001'))
            db.execute("UPDATE knowledge SET content='owner custom account rule' WHERE id='ACCOUNT-001'")
            db.execute("DELETE FROM settings WHERE key='business_rules_v3_migrated'")
            db.set_setting('auto_balance_fix', True)
            db.set_setting('reply_mode', 'review')
            db.close()
            db = Database(path)
            try:
                self.assertIn('5 美元', db.one("SELECT content FROM knowledge WHERE id='BAL-001'")['content'])
                self.assertEqual('owner custom account rule', db.one("SELECT content FROM knowledge WHERE id='ACCOUNT-001'")['content'])
                self.assertFalse(db.settings()['auto_balance_fix'])
                self.assertEqual('review', db.settings()['reply_mode'])
                self.assertEqual([], db.all('PRAGMA foreign_key_check'))
                self.assertEqual(-1800, db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])
            finally:
                db.close()

    def test_staff_invoice_route_and_customer_permission(self):
        app = PortalApplication(self.service)
        tid = self.ticket('发票修改', self.cora)
        invoice = self.service.account(self.cora)['invoices'][0]
        path = f"/api/staff/tickets/{tid}/invoices/{invoice['id']}"
        self.assert_denied(403, app.dispatch, 'POST', path, self.cora, self.invoice_payload(invoice))
        result = app.dispatch('POST', path, self.staff, self.invoice_payload(invoice))
        self.assertIn('更新后的演示抬头', result['messages'][-1]['content'])


class TimeInterpretationTests(unittest.TestCase):
    def parse(self, text, **payload):
        return parse_context(text, payload, received_at='2026-11-04T10:00:00+00:00')

    def test_same_wall_clock_and_same_instant_are_distinct(self):
        self.assertEqual('2026-11-04T09:56:00+00:00', self.parse('2026-11-04 20:56 UTC+11')['start_utc'])
        self.assertEqual('2026-11-04T12:56:00+00:00', self.parse('2026-11-04 20:56 UTC+8')['start_utc'])
        self.assertEqual('2026-11-04T17:56:00+08:00', time_evidence('2026-11-04T09:56:00+00:00', 'Asia/Shanghai')['local'])

    def test_explicit_event_timezone_overrides_browser(self):
        result = self.parse('2026-11-04 20:56 北京时间', time_zone='Australia/Sydney', timezone_source='browser')
        self.assertEqual(('2026-11-04T12:56:00+00:00', 'explicit'), (result['start_utc'], result['timezone_source']))

    def test_cross_day_and_historical_dst_use_event_date(self):
        self.assertEqual('2026-11-03T13:05:00+00:00', self.parse('2026-11-04 00:05 悉尼时间')['start_utc'])
        self.assertEqual('2026-07-04T10:56:00+00:00', self.parse('2026-07-04 20:56 悉尼时间')['start_utc'])

    def test_dst_duplicate_and_nonexistent_times_need_clarification(self):
        duplicate = self.parse('2026-04-05 02:30 悉尼时间')
        missing = self.parse('2026-10-04 02:30 悉尼时间')
        self.assertIn('两次', duplicate['time_issue'])
        self.assertIn('不存在', missing['time_issue'])
        self.assertNotIn('start_utc', duplicate)
        self.assertNotIn('start_utc', missing)

    def test_explicit_offset_resolves_dst_duplicate_and_iso_is_accepted(self):
        first = self.parse('2026-04-05 02:30 UTC+11')
        second = self.parse('2026-04-05T02:30+10:00')
        self.assertEqual(timedelta(hours=1), datetime.fromisoformat(second['start_utc']) - datetime.fromisoformat(first['start_utc']))


if __name__ == '__main__':
    unittest.main()

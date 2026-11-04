"""Owner-approved automation, administrator evidence, and usage accounting."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from support_agent.desk.admin import AdminConsole
from support_agent.desk.audit import run_receipt, usage_summary, valid_prices
from support_agent.desk.engine import quality_check
from support_agent.desk.model import DeskModel
from support_agent.desk.service import DeskError, DeskService
from support_agent.desk.storage import Database, after, now
from support_agent.portal import PortalApplication
from test_model_context import ContextProvider


class ApprovedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.service = DeskService(self.db, seed_tickets=False)
        self.console = AdminConsole(self.service)
        self.admin, self.alice, self.ben, self.staff = [self.db.one('SELECT * FROM users WHERE id=?', (i,)) for i in (1, 2, 3, 5)]

    def create(self, query, user=None):
        return self.service.create_ticket(user or self.alice, {'subject': 'Acceptance', 'content': query})['ticket']['id']

    def run_for(self, tid):
        return self.service.decode_run(self.db.one('SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1', (tid,)))

    def balance(self):
        return self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units']

    def debt(self, units, kind='request_overage'):
        self.db.execute('UPDATE users SET balance_units=? WHERE id=2', (-units,))
        self.db.execute('INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,?,?,?,\'test\',?)',
                        (kind, -units, -units, now()))

    def fixes(self):
        return self.db.one("SELECT COUNT(*) n FROM ledger WHERE kind='balance_fix'")['n']

    def denied(self, fn, *args):
        with self.assertRaises(DeskError) as caught:
            fn(*args)
        self.assertEqual(403, caught.exception.status)

    def test_auto_write_receipt_is_internal_and_idempotent(self):
        tid = self.create('帮我回正余额')
        run = self.run_for(tid)
        self.assertEqual(('sent', 0, 1), (run['state'], self.balance(), self.fixes()))
        for person in (self.admin, self.staff):
            messages = self.service.ticket_detail(person, tid)['messages']
            self.assertTrue(any(m['visibility'] == 'staff' and '回正成功' in m['content'] and '$0.0000' in m['content'] for m in messages))
        customer = self.service.ticket_detail(self.alice, tid)
        self.assertTrue(all(m['visibility'] == 'public' for m in customer['messages']))
        self.assertNotIn('回正成功', json.dumps(customer, ensure_ascii=False))
        self.assertNotIn('回正成功', self.service.list_tickets(self.alice)[0]['preview'])
        self.assertEqual(0, self.service.account(self.alice)['user']['balance_units'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.service.publish(None, run['id'], {'execute_actions': True}, automatic=True), range(2)))
        self.assertEqual(1, self.fixes())

    def test_plain_query_and_policy_question_do_not_write(self):
        for query in ('查询余额', '什么条件下能把负余额回正？', '查询 cora@lumen.test 的余额', '只查负余额，不要操作'):
            tid = self.create(query)
            self.assertEqual([], self.run_for(tid)['actions'], query)
            self.assertEqual(-1800, self.balance())
        self.assertEqual(0, self.fixes())

    def test_small_debt_has_no_cooldown_and_large_debt_has_one(self):
        self.debt(60000)
        self.create('帮我回正余额')
        self.assertEqual(0, self.balance())
        self.debt(70000)
        tid = self.create('帮我回正余额')
        self.assertEqual(-70000, self.balance())
        self.assertIn('小额充值', self.run_for(tid)['answer'])
        self.debt(50000)
        self.create('帮我回正余额')
        self.assertEqual(0, self.balance())
        self.assertEqual(2, self.fixes())

    def test_recharge_bypasses_provenance_and_cooldown_only_for_staff(self):
        self.debt(60000)
        self.create('帮我回正余额')
        self.debt(70000, 'admin_adjustment')
        tid = self.create('查询余额')
        public_before = self.service.ticket_detail(self.alice, tid)['messages']
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda person: self.service.human_reply(person, tid, {'content': '/recharge'}), (self.staff, self.admin)))
        self.assertEqual((0, 2), (self.balance(), self.fixes()))
        self.assertEqual(public_before, self.service.ticket_detail(self.alice, tid)['messages'])
        self.assertTrue(self.service.ticket_detail(self.staff, tid)['human_priority'])

    def test_customer_command_and_personal_staff_cannot_mutate(self):
        tid = self.create('/recharge')
        self.assertEqual((-1800, 0), (self.balance(), self.fixes()))
        for person in (self.alice, {**self.staff, 'view_mode': 'personal'}, {**self.admin, 'view_mode': 'personal'}):
            self.denied(self.service.human_reply, person, tid, {'content': '/recharge'})
        self.assertEqual(-1800, self.balance())

    def test_override_rejects_amount_and_preserves_positive_balance(self):
        tid = self.create('查询余额', self.ben)
        original = self.service.account(self.ben)['user']['balance_units']
        with self.assertRaises(DeskError):
            self.service.human_reply(self.staff, tid, {'content': '/recharge 100'})
        self.service.human_reply(self.staff, tid, {'content': '/recharge'})
        self.assertEqual(original, self.service.account(self.ben)['user']['balance_units'])
        self.assertEqual(0, self.fixes())
        self.assertIn('无需回正', self.service.ticket_detail(self.staff, tid)['messages'][-1]['content'])

    def test_override_failure_rolls_back_receipt_and_ledger(self):
        tid = self.create('查询余额')
        before = self.service.ticket_detail(self.staff, tid)['messages']
        with patch.object(self.db, 'event', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                self.service.human_reply(self.staff, tid, {'content': '/recharge'})
        self.assertEqual((-1800, 0), (self.balance(), self.fixes()))
        self.assertEqual(before, self.service.ticket_detail(self.staff, tid)['messages'])

    def test_global_switch_and_human_takeover_block_auto_writes(self):
        self.db.set_setting('reply_mode', 'review')
        tid = self.create('帮我回正余额')
        self.service.run_due_jobs()
        self.assertEqual((-1800, 0), (self.balance(), self.fixes()))
        self.db.set_setting('reply_mode', 'auto')
        self.service.ticket_action(self.staff, tid, {'action': 'takeover'})
        self.service.customer_message(self.alice, tid, {'content': '现在帮我回正余额'})
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE state='queued'", (after(seconds=-1),))
        self.service.run_due_jobs()
        self.assertEqual('draft', self.run_for(tid)['state'])
        self.assertEqual((-1800, 0), (self.balance(), self.fixes()))
        self.service.publish(self.staff, self.run_for(tid)['id'], {'execute_actions': True})
        self.assertEqual(0, self.balance())

    def test_basis_precedes_final_and_is_filtered_at_api_boundary(self):
        self.service.workflow.model = DeskModel(ContextProvider())
        tid = self.create('gpt-6.1-sol 返回 403，套餐用光，余额兜底关闭', self.ben)
        admin = self.service.ticket_detail(self.admin, tid)
        basis = [m for m in admin['messages'] if m['visibility'] == 'admin']
        self.assertEqual(1, len(basis))
        self.assertIn('ERR-401', basis[0]['content'])
        self.assertIn('PLAN-001', basis[0]['content'])
        self.assertIn('get_api_keys', basis[0]['content'])
        self.assertIn('BM25', basis[0]['content'])
        self.assertLess(basis[0]['id'], admin['messages'][-1]['id'])
        run = admin['runs'][0]
        self.assertEqual('openai', run['provider'])
        self.assertEqual(3, len(run['quality']['model']['calls']))
        self.assertIn('模型依据摘要', basis[0]['content'])
        for person in (self.staff, self.ben):
            rendered = json.dumps(self.service.ticket_detail(person, tid), ensure_ascii=False)
            for private in ('admin_basis', 'BM25', 'get_api_keys', 'PLAN-001', 'ERR-401', 'evidence_summary'):
                self.assertNotIn(private, rendered)
        self.assertNotIn('BM25', json.dumps(self.console.dashboard(self.staff), ensure_ascii=False))

    def test_admin_personal_view_and_model_history_exclude_private_messages(self):
        personal_admin = {**self.admin, 'view_mode': 'personal'}
        tid = self.create('套餐先扣哪一份？', personal_admin)
        detail = self.service.ticket_detail(personal_admin, tid)
        self.assertTrue(all(m['visibility'] == 'public' for m in detail['messages']))
        self.assertNotIn('runs', detail)
        self.service.customer_message(personal_admin, tid, {'content': '换个问题：Codex 怎么配置？'})
        ticket = self.db.one('SELECT * FROM tickets WHERE id=?', (tid,))
        trigger = self.db.one("SELECT * FROM messages WHERE ticket_id=? AND role='customer' ORDER BY id DESC LIMIT 1", (tid,))
        history = self.service.workflow.conversation_context(ticket, trigger, {})
        self.assertNotIn('BM25', json.dumps(history, ensure_ascii=False))

    def test_unsubstantiated_model_citations_are_not_displayed(self):
        tid = self.create('查询余额')
        run = self.run_for(tid)
        run.update(provider='openai', model_evidence_summary='依据 FAKE-999 可确认。')
        self.assertNotIn('FAKE-999', run_receipt(run)['summary'])

    def test_customer_reply_quality_rejects_private_trace_or_command(self):
        for private in ('依据 ERR-401 和 PLAN-001', 'BM25 检索后', 'get_api_keys 已查询', '请发送 /recharge', 'evidence_summary'):
            self.assertFalse(quality_check(private, '请核对客户端设置。')['passed'], private)
        self.assertTrue(quality_check('gpt-6.1-sol：请核对客户端设置。', '请核对客户端设置。')['passed'])

    def test_image_placeholder_requests_only_missing_text(self):
        tid = self.create('我用 Codex，模型 gpt-6.1-sol，这个截图的报错是什么意思？')
        run = self.run_for(tid)
        self.assertIn('没有可读取的图片', run['answer'])
        self.assertIn('完整错误文字', run['answer'])
        self.assertNotIn('get_recent_requests', [t['name'] for t in run['tools']])
        self.assertNotIn('使用的客户端、模型名称', run['answer'])

    def test_private_suggestion_keeps_send_controls_without_exposing_basis(self):
        tid = self.create('套餐额度是多少？', self.ben)
        self.service.human_reply(self.staff, tid, {'content': '我来跟进'})
        self.service.customer_message(self.ben, tid, {'content': '换个问题：余额是多少？'})
        self.assertEqual('suggestion_pending', self.service.ticket_detail(self.ben, tid)['reply_state'])
        self.assertEqual(0, self.service.run_due_jobs())
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE state='queued'", (after(seconds=-1),))
        self.service.run_due_jobs()
        draft = self.service.ticket_detail(self.staff, tid)['runs'][0]
        self.assertEqual('draft', draft['state'])
        self.assertIn('15 分钟', draft['blocked_reason'])
        self.assertNotIn('admin_basis', draft)
        self.service.publish(self.staff, draft['id'], {})
        self.assertEqual('assistant', self.service.ticket_detail(self.ben, tid)['messages'][-1]['role'])

    def test_unknown_knowledge_transfers_and_dynamic_balance_does_not(self):
        for query in ('gpt-6.1-sol 的上下文窗口上限是多少 Token？', '错误码是 1401，不是 401', '发票有导出 Excel 的 API 吗？'):
            tid = self.create(query)
            run = self.run_for(tid)
            self.assertEqual([], run['evidence'])
            self.assertEqual('waiting_human', self.service.ticket_detail(self.alice, tid)['ticket']['status'])
            self.assertIn('人工', run['answer'])
        tid = self.create('只查当前余额还有多少钱？')
        self.assertEqual('waiting_customer', self.service.ticket_detail(self.alice, tid)['ticket']['status'])
        self.assertIn('-0.1800', self.run_for(tid)['answer'])

    def test_duration_requires_one_exact_current_account_request(self):
        record = self.db.one('SELECT * FROM request_logs WHERE user_id=3 ORDER BY id DESC LIMIT 1')
        tid = self.create(f"请求 #{record['id']} 的日志用了多少毫秒？", self.ben)
        self.assertIn(str(record['latency_ms']) + ' 毫秒', self.run_for(tid)['answer'])
        other = self.create(f"请求 #{record['id']} 的日志用了多少毫秒？", self.alice)
        self.assertIn('无法唯一确定', self.run_for(other)['answer'])
        uncertain = self.create('刚才那次请求用了多少毫秒？', self.ben)
        self.assertIn('无法唯一确定', self.run_for(uncertain)['answer'])

    def test_static_topic_switch_then_return_uses_fresh_data(self):
        tid = self.create('我要申请退款', self.ben)
        self.service.customer_message(self.ben, tid, {'content': '退款先放一边，现在只问套餐和余额先扣哪一份？'})
        self.assertEqual(['quota'], self.run_for(tid)['intents'])
        self.db.execute('UPDATE subscriptions SET used_units=1230000 WHERE user_id=3')
        self.service.customer_message(self.ben, tid, {'content': '那我的套餐还剩多少？'})
        run = self.run_for(tid)
        self.assertIn('get_subscriptions', [t['name'] for t in run['tools']])
        self.assertNotIn('get_orders', [t['name'] for t in run['tools']])
        self.service.customer_message(self.ben, tid, {'content': '回到最开始的问题，进度怎么样？'})
        self.assertIn('get_orders', [t['name'] for t in self.run_for(tid)['tools']])

    def test_usage_endpoint_is_admin_only(self):
        app = PortalApplication(self.service)
        self.assertEqual(0, app.dispatch('GET', '/api/admin/usage', self.admin, {})['calls'])
        self.assertNotIn('model_prices', self.console.dashboard(self.staff)['settings'])
        self.assertIn('model_prices', self.console.dashboard(self.admin)['settings'])
        for person in (self.staff, self.alice, {**self.admin, 'view_mode': 'personal'}):
            self.denied(app.dispatch, 'GET', '/api/admin/usage', person, {})


class UsageAccountingTests(unittest.TestCase):
    def test_retries_and_missing_usage_are_not_zero_cost(self):
        run = {'quality': {'model': {'requested_model': 'configured-model', 'calls': [
            {'ok': False, 'stage': 'support_reply', 'attempt': 1, 'elapsed_ms': 20},
            {'ok': True, 'stage': 'support_reply', 'attempt': 2, 'elapsed_ms': 30,
             'response_model': 'snapshot', 'usage': {'prompt_tokens': 100, 'completion_tokens': 50}},
        ]}}}
        rate = {'configured-model': {'input_per_million': 2, 'output_per_million': 8, 'currency': 'USD'}}
        result = usage_summary([run], rate)
        self.assertEqual((2, 1, 1, 1, 100, 50, 50), tuple(result[k] for k in ('calls', 'failed_calls', 'retries', 'usage_missing_calls', 'input_tokens', 'output_tokens', 'model_elapsed_ms')))
        self.assertAlmostEqual(0.0006, result['cost_by_currency']['USD'])
        self.assertFalse(result['cost_complete'])
        self.assertEqual(1, usage_summary([run])['unpriced_calls'])

    def test_rates_validate_and_local_cost_is_zero_without_embedding_calls(self):
        self.assertTrue(valid_prices({'m': {'input_per_million': 0, 'output_per_million': 1.5, 'currency': 'USD'}}))
        for rate in (-1, float('nan'), float('inf'), True, '2'):
            self.assertFalse(valid_prices({'m': {'input_per_million': rate, 'output_per_million': 1, 'currency': 'USD'}}))
        self.assertEqual((0, True), (usage_summary([])['calls'], usage_summary([])['cost_complete']))


if __name__ == '__main__':
    unittest.main()

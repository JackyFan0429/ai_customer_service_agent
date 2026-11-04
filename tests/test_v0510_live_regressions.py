"""Regressions found while preparing and running real-model acceptance."""
import unittest

from support_agent.desk.knowledge import query_scope
from support_agent.desk.audit import run_receipt
from support_agent.desk.engine import quality_check
from support_agent.desk.evidence import money_claims
from decimal import Decimal
from support_agent.desk.service import DeskService
from support_agent.desk.storage import Database
from support_agent.desk.storage import now
from support_agent.desk.model import DeskModel
from test_multiturn_regression import ReplayProvider


class NaturalErrorReferenceTests(unittest.TestCase):
    def test_error_code_can_touch_chinese_but_not_another_identifier(self):
        for text, expected in [('提示403，余额兜底关闭', {'ERR-401', 'PLAN-001'}),
                               ('刚才的503请求失败', {'ERR-503'})]:
            with self.subTest(text=text):
                self.assertTrue(expected.issubset(query_scope(text)['ids']))
        for text in ('错误码1401是什么意思', '错误码1403是什么意思'):
            with self.subTest(text=text):
                scope = query_scope(text)
                self.assertEqual('missing', scope['mode'])
                self.assertEqual([], scope['ids'])
        for text in ('E401', 'x403', '4037', '1503'):
            with self.subTest(text=text):
                self.assertFalse(set(query_scope(text)['ids']) & {'ERR-401', 'ERR-503'})

    def test_returning_to_403_keeps_combined_evidence_without_refund(self):
        db = Database(':memory:')
        self.addCleanup(db.close)
        service = DeskService(db, seed_tickets=False)
        customer = db.one('SELECT * FROM users WHERE id=3')
        tid = service.create_ticket(customer, {'subject': 'Topic return', 'content': 'gpt-6.1-sol 返回 403。套餐有效但额度用光了，余额兜底关闭。'})['ticket']['id']
        service.customer_message(customer, tid, {'content': '先不管403，换个问题：退款会让套餐额度马上刷新吗？只咨询，不提交申请。'})
        service.customer_message(customer, tid, {'content': '回到刚才的403：账户余额是正数就能绕过关闭的余额兜底吗？'})
        run = service.decode_run(db.one('SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1', (tid,)))
        self.assertEqual({'ERR-401', 'PLAN-001'}, {e['id'] for e in run['evidence']})
        self.assertNotIn('退款', run['answer'])
        self.assertEqual([], run['actions'])

    def test_short_403_followup_includes_policy_dependency(self):
        scope = query_scope('还是403。模型和客户端都没变，也没有请求编号；请继续核查账号配置，不要让我重复报这些信息。')
        self.assertEqual({'ERR-401', 'PLAN-001'}, set(scope['ids']))
        self.assertNotIn('PLAN-001', query_scope('还是401，已经核对配置')['ids'])
        self.assertNotIn('ERR-401', query_scope('先不管403，换个问题：退款怎么处理')['ids'])

    def test_receipt_distinguishes_financial_template_from_failed_model(self):
        run = {'tools': [], 'evidence': [], 'intents': ['balance'], 'route': 'answer',
               'provider': 'local', 'quality': {'passed': True, 'model_fallback': False,
                 'model': {'source': 'policy', 'calls': [{'stage': 'support_intents', 'ok': True}]}}}
        receipt = run_receipt(run)['summary']
        self.assertIn('财务固定模板', receipt)
        self.assertIn('真实模型分诊成功', receipt)
        self.assertIn('未发生模型回退', receipt)
        run['quality']['model_fallback'] = True
        run['quality']['model']['calls'] = [{'stage': 'support_intents', 'ok': False}]
        receipt = run_receipt(run)['summary']
        self.assertNotIn('真实模型分诊成功', receipt)
        self.assertNotIn('未发生模型回退', receipt)
        self.assertIn('发生模型回退', receipt)


class DebtExpressionTests(unittest.TestCase):
    baseline = '当前余额 $-7.0000。过去 7 天已成功回正过超过 5 美元的欠款；请小额充值补足欠款，需人工核账。'
    facts = [{'name': 'get_account_overview', 'status': 'ok', 'result': {'balance_units': -70000}}]

    def test_minus_before_currency_is_preserved(self):
        for text in ('-$7.0000', '$-7', '-7美元', '−$7'):
            with self.subTest(text=text):
                self.assertEqual([('USD', Decimal('-7'))], [v for _, _, v in money_claims(text)])

    def test_observed_real_model_debt_reply_passes(self):
        reply = '已核验，你当前的账户余额为 -$7.0000。由于本次欠款超过 $5，且过去 7 天内已有超过 $5 的成功回正记录，本次不能再直接自动回正，余额尚未变更。\n\n请小额充值补足当前 $7 欠款；如需进一步核账，需要人工处理。'
        self.assertTrue(quality_check(reply, self.baseline, facts=self.facts)['passed'])
        self.assertTrue(quality_check('当前负余额7美元，请充值补足$7欠款。', self.baseline, facts=self.facts)['passed'])

    def test_debt_magnitude_cannot_authorize_positive_balance_or_refund(self):
        for reply in ('当前账户余额为 $7。', '可退金额为 $7。', '已充值 $7 补足欠款。',
                      '请补足 $8 欠款。', '请补足 ¥7 欠款。'):
            with self.subTest(reply=reply):
                self.assertFalse(quality_check(reply, self.baseline, facts=self.facts)['passed'])

    def test_historical_negative_balance_cannot_authorize_current_debt(self):
        context = {'conversation': [{'speaker': 'human', 'content': '旧余额为 -$7。'}]}
        facts = [{'name': 'get_account_overview', 'status': 'ok', 'result': {'balance_units': 70000}}]
        self.assertFalse(quality_check('当前账户余额为 -$7。', '当前账户余额 $7。', facts=facts, context=context)['passed'])
        self.assertFalse(quality_check('请补足 $7 欠款。', '余额已清零。', facts=[], context=context)['passed'])

    def test_debt_reply_publishes_without_wasted_repair_calls(self):
        db = Database(':memory:')
        self.addCleanup(db.close)
        provider = ReplayProvider()
        provider.reply = '当前账户余额为 -$7.0000。过去 7 天已有超过 $5 的成功回正，本次不能自动回正；请小额充值补足当前 $7 欠款，需要人工核账。'
        service = DeskService(db, DeskModel(provider), seed_tickets=False)
        db.execute('UPDATE users SET balance_units=-70000 WHERE id=2')
        for kind, delta, balance in [('balance_fix', 60000, 0), ('request_overage', -70000, -70000)]:
            db.execute('INSERT INTO ledger(user_id,kind,delta_units,balance_after_units,note,created_at) VALUES (2,?,?,?,?,?)', (kind, delta, balance, 'acceptance regression', now()))
        customer = db.one('SELECT * FROM users WHERE id=2')
        tid = service.create_ticket(customer, {'subject': 'Repeated debt', 'content': '我有7美元负余额，刚回正过6美元，现在能再回正吗？'})['ticket']['id']
        run = service.decode_run(db.one('SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1', (tid,)))
        self.assertEqual(('openai', 'sent'), (run['provider'], run['state']))
        self.assertFalse(run['quality']['model_fallback'])
        self.assertFalse(run['quality']['revision_attempted'])
        self.assertEqual(['support_intents', 'support_reply', 'support_quality'], [name for name, _ in provider.requests])
        self.assertEqual(-70000, service.account(customer)['user']['balance_units'])


if __name__ == '__main__':
    unittest.main()

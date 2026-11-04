"""Sanitized export-inspired multi-turn cases and numeric evidence boundaries."""

import json
import unittest

from support_agent.desk.engine import local_intents, quality_check
from support_agent.desk.model import DeskModel
from support_agent.desk.service import DeskError, DeskService
from support_agent.desk.storage import Database, after
from support_agent.providers import ResponsesProvider


class ReplayProvider(ResponsesProvider):
    def __init__(self):
        super().__init__('test-only-key', 'gpt-6-astra')
        self.reply = None
        self.requests = []

    def _request(self, payload):
        stage = payload['text']['format']['name']
        data = json.loads(payload['input'])
        self.requests.append((stage, data))
        if stage == 'support_intents':
            result = {'intents': local_intents(data['message'], {'intents': data['history']['previous_intents']})}
        elif stage == 'support_reply':
            result = {'evidence_summary': '依据本次业务查询回复。', 'answer': self.reply or data['baseline_answer']}
        else:
            result = {'issues': []}
        return {'model': 'gpt-6-astra-test', 'output_text': json.dumps(result, ensure_ascii=False)}


class EvidenceBoundaryTests(unittest.TestCase):
    def check(self, answer, **kwargs):
        return quality_check(answer, '当前余额 $18.50，订单实付 ¥99，查询 12 条记录。', **kwargs)['passed']

    def test_known_time_error_and_human_steps_are_not_new_financial_facts(self):
        context = {'conversation': [
            {'speaker': 'customer', 'content': '22:26（悉尼时间），HTTP 503，完整错误是 upstream unavailable。'},
            {'speaker': 'human', 'content': '请将等待时间改为 90 秒。'}]}
        self.assertTrue(self.check('收到你 22:26 遇到的 HTTP 503；你已按客服建议等待 90 秒，不用重复提供。', context=context))
        self.assertFalse(self.check('已扣费 $503。', context=context))
        self.assertFalse(self.check('当前余额为 503。', context=context))

    def test_current_tool_money_is_converted_from_integer_storage_units(self):
        facts = [{'result': {'failed_cost_units': 0, 'balance_units': 185000, 'amount_cents': 9900}}]
        self.assertTrue(self.check('失败记录合计 $0.00，余额 $18.5000，订单 ¥99.00。', facts=facts))
        self.assertFalse(self.check('余额 $185000。', facts=facts))
        self.assertFalse(self.check('订单 $99。', facts=facts))

    def test_requested_retained_balance_is_not_refund_approval(self):
        query = '想退款，留 $5 继续用。'
        self.assertTrue(self.check('已记录你希望保留 $5 的诉求，退款金额需人工核验。', query=query))
        self.assertTrue(self.check('客服登记的是你最新的剩余全部余额申请，不再是留 $5 的方案。', query=query))
        self.assertTrue(self.check('明白，你希望退还部分账户余额，保留 $5 继续使用。', query=query))
        for answer in ['当前余额 $5。', '可退金额为 $5。', '你希望保留 $5，已经退款 $5。', '你希望保留 $5，可退金额为 $5。', '申请退款金额为 $13.50。', '你希望退款，保留 $5，所以可以退 $5。', '你希望退款。当前余额 $5。']:
            self.assertFalse(self.check(answer, query=query), answer)

    def test_old_ai_or_human_amounts_cannot_authorize_current_balance(self):
        context = {'conversation': [{'speaker': 'ai', 'content': '余额 $999。'}, {'speaker': 'human', 'content': '退款金额为 $999。'}]}
        self.assertFalse(self.check('当前余额 $999。', context=context))
        self.assertFalse(self.check('退款金额为 999。', context=context))

    def test_list_numbers_and_model_versions_are_not_business_amounts(self):
        self.assertTrue(self.check('1. 你使用 claude-opus-4-8。\n2. 余额 $18.50。'))

    def test_denied_promises_are_not_completed_actions(self):
        self.assertTrue(self.check('不能保证到账时间，也无法确认已经退款。'))
        self.assertFalse(self.check('不能保证到账时间，但已经退款。'))
        self.assertFalse(quality_check('已经退款。', '无法确认已经退款。')['passed'])


class MultiTurnRegressionTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.provider = ReplayProvider()
        self.service = DeskService(self.db, DeskModel(self.provider), seed_tickets=False)
        self.customer = self.db.one('SELECT * FROM users WHERE id=3')
        self.staff = self.db.one('SELECT * FROM users WHERE id=5')

    def create(self, text):
        return self.service.create_ticket(self.customer, {'subject': '多轮回归', 'content': text})['ticket']['id']

    def latest(self, tid):
        return self.service.ticket_detail(self.db.one('SELECT * FROM users WHERE id=1'), tid)['runs'][0]

    def test_contextual_reply_passes_generation_and_publication(self):
        tid = self.create('Claude Code 使用 claude-opus-4-8；22:26 悉尼时间报错503，完整错误是 upstream unavailable。')
        self.provider.reply = '已收到你在 22:26 遇到的 HTTP 503，完整错误和客户端不用重复提供。'
        self.service.customer_message(self.customer, tid, {'content': '刚才那个问题还是一样，我没有请求编号。'})
        run = self.latest(tid)
        self.assertEqual(('openai', 'sent'), (run['provider'], run['state']))
        self.assertFalse(run['quality']['model_fallback'])
        self.assertFalse(run['quality']['revision_attempted'])
        self.assertEqual(self.provider.reply, self.service.ticket_detail(self.customer, tid)['messages'][-1]['content'])

    def test_retained_amount_can_be_quoted_without_local_fallback(self):
        self.provider.reply = '已记录你希望保留 $5 的诉求。当前余额为 $18.50；是否可退、可退金额和手续费由人工核验。'
        tid = self.create('我用不了这么多，想申请退还一部分余额，留 $5 继续用。')
        run = self.latest(tid)
        self.assertEqual(('openai', 'sent'), (run['provider'], run['state']))
        self.assertNotIn('technical', run['intents'])
        self.assertNotIn('get_recent_requests', [t['name'] for t in run['tools']])

    def test_omitted_refund_subject_still_fetches_current_order_state(self):
        tid = self.create('我想申请退款。')
        self.service.customer_message(self.customer, tid, {'content': '好的'})
        self.service.customer_message(self.customer, tid, {'content': '那现在到哪一步了？还需要我重新提交订单或再开工单吗？'})
        run = self.latest(tid)
        self.assertIn('get_orders', [t['name'] for t in run['tools']])
        self.assertIn('refund', run['intents'])

    def test_natural_recovery_confirmation_closes_both_views(self):
        tid = self.create('Claude Code 报错 503，想核对是否扣费。')
        self.service.customer_message(self.customer, tid, {'content': '确认，已经可以正常用了。我不再追查这次扣费，可以结束这个工单，谢谢。'})
        run = self.latest(tid)
        self.assertEqual(['resolved'], run['intents'])
        self.assertEqual(('openai', 'sent'), (run['provider'], run['state']))
        for user in (self.customer, self.staff):
            self.assertEqual('resolved', self.service.ticket_detail(user, tid)['ticket']['status'])

    def test_recovery_variations_do_not_close_uncertain_or_pending_work(self):
        for text in ['已经可以正常使用了，谢谢。', '恢复正常了，可以结束工单。']:
            self.assertEqual(['resolved'], local_intents(text, {}), text)
        self.assertEqual(['resolution_check'], local_intents('现在应该可以正常用了。', {}))
        for text in ['已经可以正常用了，但是扣费还没核实。', '已经可以正常用了，扣费还未确认。', '不是已经可以正常用了，仍然报错。', '可以正常使用了吗？', '什么时候恢复正常', '还没有恢复正常']:
            self.assertNotEqual(['resolved'], local_intents(text, {}), text)

    def test_local_outage_reply_does_not_repeat_provided_details(self):
        self.service.workflow.model = None
        tid = self.create('Claude Code 报错503，22:26 悉尼时间，完整错误是 upstream unavailable。我重启试过了。')
        self.service.customer_message(self.customer, tid, {'content': '还是一样，我没有请求编号，信息已经发过。'})
        answer = self.latest(tid)['answer']
        self.assertIn('无需重复', answer)
        self.assertNotIn('请补充', answer)
        self.assertIn('没有请求编号', answer)

    def test_fee_question_alone_does_not_register_a_refund(self):
        tid = self.create('退款会收手续费吗？')
        run = self.latest(tid)
        self.assertEqual([], run['actions'])
        self.assertIn('没有可确认的费率', run['answer'])

    def test_refund_human_context_remains_private_and_can_publish(self):
        tid = self.create('申请退款，保留 $5 继续用。')
        self.service.human_reply(self.staff, tid, {'content': '已收到你改为退剩余全部余额的申请，金额和手续费尚未批准。'})
        self.service.customer_message(self.customer, tid, {'content': '客服登记的那笔有没有结果，还是没批准？'})
        self.assertEqual(1, self.db.one("SELECT COUNT(*) AS n FROM generation_jobs WHERE ticket_id=? AND state='queued'", (tid,))['n'])
        self.provider.reply = '你最新申请的是剩余全部余额；如客服所说，目前仍待人工核验，不能确认退款已完成，手续费也未确认。'
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE ticket_id=?", (after(seconds=-1), tid))
        self.service.run_due_jobs()
        run = self.latest(tid)
        self.assertEqual(('openai', 'draft'), (run['provider'], run['state']))
        self.assertTrue(run['quality']['model']['includes_human'])
        self.assertIn('get_orders', [t['name'] for t in run['tools']])
        self.assertEqual('customer', self.service.ticket_detail(self.customer, tid)['messages'][-1]['role'])
        with self.assertRaises(DeskError):
            self.service.publish(self.staff, run['id'], {'content': '当前余额 $503。'})
        self.service.publish(self.staff, run['id'], {})
        self.assertEqual(self.provider.reply, self.service.ticket_detail(self.customer, tid)['messages'][-1]['content'])


if __name__ == '__main__':
    unittest.main()

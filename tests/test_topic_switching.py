"""Topic changes must not reuse stale facts or authorize unrelated operations."""
import json
import unittest
from unittest.mock import patch

from support_agent.desk.engine import local_intents, quality_check
from support_agent.desk.model import DeskModel
from support_agent.desk.service import DeskError, DeskService
from support_agent.desk.storage import Database, encode
from support_agent.desk.tools import display_times
from support_agent.desk.topics import remember_topic
from tests.test_multiturn_regression import ReplayProvider


class TopicRoutingTests(unittest.TestCase):
    def test_client_exit_never_means_refund(self):
        for question in ['我已经完全退出重开 Codex，模型显示 Custom', '帮我退出客户端再配置', '我想退出 Codex 然后接入模型']:
            self.assertNotIn('refund', local_intents(question, {}), question)
        for question in ['我要全退', '申请退还剩余全部余额', '我想退款']:
            self.assertIn('refund', local_intents(question, {}), question)

    def test_quota_reset_and_mentioning_staff_are_not_account_changes(self):
        self.assertEqual(['quota'], local_intents('额度能提前重置吗？', {}))
        self.assertNotIn('account', local_intents('人工客服刚才确认的退款呢？', {}))
        self.assertIn('account', local_intents('帮我重置密码', {}))
        self.assertIn('account', local_intents('我要转人工', {}))

    def test_explicit_correction_drops_old_keywords(self):
        self.assertEqual(['balance'], local_intents('不是模型配置，我问的是余额回正', {'active_intents':['configuration']}))
        self.assertEqual(['quota'], local_intents('不是模型配置而是套餐额度', {'active_intents':['configuration']}))
        self.assertEqual(['configuration'], local_intents('先别处理余额回正换个问题Codex 配置显示 Custom', {'active_intents':['balance']}))

    def test_unqualified_old_topic_is_clarified_when_multiple_candidates_exist(self):
        history = [{'intents':['quota'],'question':'套餐额度'}, {'intents':['balance'],'question':'余额'}, {'intents':['configuration'],'question':'模型配置'}]
        self.assertEqual(['unknown'], local_intents('再问之前那个问题，现在怎么样了？', {'active_intents':['configuration'],'topic_history':history}))

    def test_known_timezone_conversion_is_evidence_but_not_money(self):
        times = display_times('2026-10-21T10:48:00+00:00')
        self.assertEqual('2026-10-21 18:48 +0800', times['Asia/Shanghai'])
        self.assertEqual('2026-10-21 21:48 +1100', times['Australia/Sydney'])
        facts=[{'result': {'reset_display_times': times}}]
        self.assertTrue(quality_check('北京时间 2026年10月21日 18:48 刷新。', '', facts=facts)['passed'])
        self.assertFalse(quality_check('可退金额为 $18.48。', '', facts=facts)['passed'])

    def test_iso_date_can_be_rendered_as_chinese_without_new_numbers(self):
        facts=[{'result':{'reset_at':'2027-01-04T10:48:00+00:00'}}]
        self.assertTrue(quality_check('2027年1月4日 10:48（UTC）刷新。','',facts=facts)['passed'])
        self.assertFalse(quality_check('2027年1月5日 10:48（UTC）刷新。','',facts=facts)['passed'])


class TopicWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db=Database(':memory:'); self.addCleanup(self.db.close)
        self.provider=ReplayProvider()
        self.service=DeskService(self.db, DeskModel(self.provider), seed_tickets=False)
        self.admin,self.alice,self.ben=[self.db.one('SELECT * FROM users WHERE id=?',(n,)) for n in (1,2,3)]

    def create(self, user, text):
        return self.service.create_ticket(user, {'subject':'主题切换回归','content':text})['ticket']['id']

    def latest(self, tid):
        return self.service.ticket_detail(self.admin,tid)['runs'][0]

    def send(self, user, tid, text):
        self.service.customer_message(user,tid,{'content':text})
        return self.latest(tid)

    def assert_tools_absent(self, run, *names):
        self.assertFalse(set(names).intersection(t['name'] for t in run['tools']))

    def test_quota_to_configuration_does_not_query_or_repeat_suspended_topics(self):
        tid=self.create(self.ben,'套餐还剩多少，余额兜底为什么不继续用？')
        run=self.send(self.ben,tid,'先不谈套餐额度和余额了。换一个问题：我已保存配置并完全退出重开 Codex，模型显示 Custom，这代表接通了吗？')
        self.assertEqual(['configuration'],run['intents'])
        self.assertEqual(('openai','sent'),(run['provider'],run['state']))
        self.assertEqual([],run['actions'])
        self.assert_tools_absent(run,'get_account_overview','get_subscriptions','get_orders')
        self.assertNotIn('$18.50',run['answer'])
        self.assertIn('不能单独证明',run['answer'])

    def test_pending_balance_action_does_not_block_new_configuration_reply(self):
        tid=self.create(self.alice,'帮我核验余额回正')
        old=self.latest(tid)
        run=self.send(self.alice,tid,'先别处理余额回正，换个问题：Codex 配置显示 Custom，已经完全退出重开，这能证明成功吗？')
        self.assertEqual(['configuration'],run['intents'])
        self.assertEqual(('openai','sent'),(run['provider'],run['state']))
        self.assertEqual([],run['actions'])
        self.assertEqual(-1800,self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])
        with self.assertRaises(DeskError): self.service.publish(self.admin,old['id'],{'execute_actions':True})

    def test_model_cannot_reintroduce_explicitly_paused_financial_topics(self):
        tid=self.create(self.alice,'帮我回正余额')
        original=self.provider._request
        def classify_old_topics(payload):
            if payload['text']['format']['name']=='support_intents':
                return {'output_text':json.dumps({'intents':['configuration','balance','refund','quota']})}
            return original(payload)
        with patch.object(self.provider,'_request',side_effect=classify_old_topics):
            run=self.send(self.alice,tid,'先别处理余额回正，换个问题：我已经完全退出 Codex，模型配置还显示 Custom')
        self.assertEqual(['configuration'],run['intents'])
        self.assertEqual([],run['actions'])
        self.assertEqual('sent',run['state'])

    def test_ambiguous_return_does_not_guess_or_run_old_actions(self):
        tid=self.create(self.ben,'套餐额度还有多少？')
        self.send(self.ben,tid,'换个问题：当前账户余额有多少？')
        self.send(self.ben,tid,'换个问题：Codex 模型如何配置？')
        run=self.send(self.ben,tid,'再问之前那个问题，现在怎么样了？')
        self.assertEqual('clarify',run['route'])
        self.assertIn('哪一个问题',run['answer'])
        self.assertEqual([],run['actions'])
        self.assert_tools_absent(run,'get_account_overview','get_subscriptions','get_orders')

    def test_return_first_topic_fetches_fresh_subscription_and_not_setup(self):
        tid=self.create(self.ben,'周卡额度还剩多少？')
        self.send(self.ben,tid,'换个问题：Codex 模型怎么配置？')
        self.db.execute("UPDATE subscriptions SET used_units=5000000 WHERE user_id=3 AND status='active'")
        run=self.send(self.ben,tid,'回到最开始那个问题，先别讲配置。现在怎么样了？')
        self.assertEqual(['quota'],run['intents'])
        self.assertIn('$100.0000',run['answer'])
        self.assertNotIn('Base URL',run['answer'])
        self.assert_tools_absent(run,'get_orders','get_account_overview')
        self.assertTrue(run['quality']['topic']['referenced_previous_topic'])

    def test_legacy_ticket_recovers_first_topic_from_customer_history(self):
        tid=self.create(self.ben,'周卡额度还有多少？')
        self.send(self.ben,tid,'换个问题：Codex 的 Base URL 怎么配置？')
        self.db.execute('UPDATE tickets SET context_json=? WHERE id=?',(encode({'active_intents':['configuration'],'intents':['configuration']}),tid))
        run=self.send(self.ben,tid,'回到最开始那个问题，先不讲配置。现在怎么样了？')
        self.assertEqual(['quota'],run['intents'])
        self.assertIn('get_subscriptions',[t['name'] for t in run['tools']])

    def test_quota_reads_actual_fallback_metadata(self):
        tid=self.create(self.ben,'套餐额度用完了，账户有余额为什么不能继续？')
        run=self.latest(tid)
        self.assertIn('get_api_keys',[t['name'] for t in run['tools']])
        self.assertIn('兜底关闭',run['answer'])
        self.assertEqual([],run['actions'])

    def test_balance_decline_is_read_only_even_with_auto_fix_enabled(self):
        self.db.set_setting('auto_balance_fix',True)
        tid=self.create(self.alice,'不要回正，先查询余额为什么是负数。')
        run=self.latest(tid)
        self.assertEqual([],run['actions'])
        self.assertEqual(-1800,self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])
        self.assertEqual('sent',run['state'])

    def test_balance_after_approval_uses_current_value_not_old_request(self):
        tid=self.create(self.alice,'帮我回正余额')
        self.service.publish(self.admin,self.latest(tid)['id'],{'execute_actions':True})
        self.service.ticket_action(self.admin,tid,{'action':'resume'})
        self.send(self.alice,tid,'换个问题：Codex 配置显示 Custom')
        run=self.send(self.alice,tid,'回到最开始那个问题，先不讲配置。现在处理到哪一步了？')
        self.assertEqual(['balance'],run['intents'])
        self.assertIn('$0.0000',run['answer'])
        self.assertNotIn('$-0.1800',run['answer'])
        self.assertEqual([],run['actions'])
        self.assertEqual(1,self.db.one("SELECT count(*) AS n FROM ledger WHERE kind='balance_fix'")['n'])

    def test_one_topic_recovered_does_not_close_other_topics(self):
        tid=self.create(self.alice,'帮我回正余额')
        self.send(self.alice,tid,'先不谈余额，换个问题：模型配置显示 Custom')
        run=self.send(self.alice,tid,'模型配置已经可以正常使用了，谢谢。')
        self.assertEqual(['resolution_check'],run['intents'])
        self.assertNotIn('close_ticket',[a['type'] for a in run['actions']])
        self.assertNotEqual('resolved',self.service.ticket_detail(self.alice,tid)['ticket']['status'])


if __name__=='__main__': unittest.main()

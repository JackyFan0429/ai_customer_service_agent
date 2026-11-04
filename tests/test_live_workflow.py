"""Timing, live notifications, migrations and staff boundaries for the portal."""
import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support_agent.desk.admin import AdminConsole
from support_agent.desk.sandbox import simulate_request
from support_agent.desk.service import DeskError, DeskService
from support_agent.desk.storage import Database, SCHEMA, after, now, password_hash
from support_agent.desk.tools import LocalBusinessTools
from support_agent.portal import PortalApplication, make_handler
from support_agent.providers import GenerationError


class LiveWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.service = DeskService(self.db, seed_tickets=False, background=True)
        self.app = PortalApplication(self.service)
        self.console = self.app.admin
        self.admin, self.customer, self.staff = [self.db.one('SELECT * FROM users WHERE id=?', (i,)) for i in (1, 3, 5)]

    def create(self, text='Claude Code 报错503，失败请求扣费了吗？'):
        return self.service.create_ticket(self.customer, {'subject': '测试问题', 'content': text})['ticket']['id']

    def followup(self, tid, text='我的套餐额度还有多少？'):
        return self.service.customer_message(self.customer, tid, {'content': text})

    def due(self):
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE state='queued'", (after(seconds=-1),))
        self.service.run_due_jobs()

    def last_run(self, tid):
        return self.db.one('SELECT * FROM runs WHERE ticket_id=? ORDER BY id DESC LIMIT 1', (tid,))

    def denied(self, fn, *args):
        with self.assertRaises(DeskError) as caught:
            fn(*args)
        self.assertEqual(403, caught.exception.status)

    def test_default_auto_queues_then_delivers_public_answer(self):
        self.assertEqual('auto', self.db.settings()['reply_mode'])
        tid = self.create()
        detail = self.service.ticket_detail(self.customer, tid)
        self.assertEqual('generating', detail['reply_state'])
        self.assertEqual(1, len(detail['messages']))
        self.service.run_due_jobs()
        detail = self.service.ticket_detail(self.customer, tid)
        self.assertEqual('assistant', detail['messages'][-1]['role'])
        self.assertEqual('waiting_customer', detail['ticket']['status'])
        self.assertEqual('idle', detail['reply_state'])
        self.assertNotIn('runs', detail)

    def test_staff_and_admin_dashboards_include_pending_without_handoff_time(self):
        self.console.settings(self.admin, {'reply_mode':'review'})
        self.create()
        for user in (self.staff, self.admin):
            dashboard = self.app.dispatch('GET','/api/staff/dashboard',user,{})
            self.assertEqual(1,dashboard['metrics']['waiting_human'])
            self.assertEqual(0,dashboard['metrics']['overdue'])

    def test_model_fallback_automatically_delivers_new_tickets_and_followups(self):
        for stage in ('classify', 'compose', 'review', 'fabrication', 'model_rejection'):
            with self.subTest(stage=stage):
                model = Mock()
                model.classify.return_value = ['technical']
                model.compose.side_effect = lambda query, facts, baseline, **kwargs: baseline
                model.review.return_value = []
                if stage in ('classify', 'compose', 'review'):
                    getattr(model, stage).side_effect = GenerationError('private-provider-key-must-not-leak')
                elif stage == 'fabrication':
                    model.compose.side_effect = None
                    model.compose.return_value = '已经退款 $99999.00，保证到账。'
                else:
                    model.review.return_value = ['回复需要修订']
                self.service.workflow.model = model
                tid = self.create('Claude Code 使用 claude-opus-4-8 时一直报错503。失败请求扣费了吗？')
                for followup in (False, True):
                    if followup:
                        self.followup(tid, '请再查一下503请求记录和扣费')
                    self.service.run_due_jobs()
                    run = self.last_run(tid)
                    quality = json.loads(run['quality_json'])
                    self.assertEqual('sent', run['state'])
                    self.assertEqual('local', run['provider'])
                    self.assertEqual('', run['blocked_reason'])
                    self.assertTrue(quality['model_fallback'])
                    self.assertTrue(quality['passed'])
                    self.assertEqual([], quality['blocking_warnings'])
                    self.assertEqual(run['baseline_answer'], run['answer'])
                    public = self.service.ticket_detail(self.customer, tid)
                    self.assertEqual('assistant', public['messages'][-1]['role'])
                    self.assertIsNone(public['messages'][-1]['author_id'])
                    self.assertIsNone(public['ticket']['human_until'])
                    self.assertNotIn('99999', public['messages'][-1]['content'])
                    self.assertNotIn('private-provider-key', json.dumps(self.service.ticket_detail(self.staff, tid)))
                sent = self.db.all("SELECT actor_id,detail FROM events WHERE ticket_id=? AND kind='ai_sent'", (tid,))
                self.assertEqual(2, len(sent))
                self.assertTrue(all(e['actor_id'] is None and e['detail'] == '自动回复已发送' for e in sent))

    def test_model_fallback_with_missing_business_evidence_stays_private(self):
        model = Mock()
        model.classify.side_effect = GenerationError('unavailable')
        self.service.workflow.model = model
        tid = self.create()
        original = LocalBusinessTools.call
        def missing_requests(tools, name, **args):
            if name == 'get_recent_requests':
                raise RuntimeError('database query unavailable')
            return original(tools, name, **args)
        with patch.object(LocalBusinessTools, 'call', missing_requests):
            self.service.run_due_jobs()
        run = self.last_run(tid)
        quality = json.loads(run['quality_json'])
        self.assertEqual('draft', run['state'])
        self.assertTrue(quality['model_fallback'])
        self.assertTrue(quality['blocking_warnings'])
        self.assertIn('业务查询未完成', run['blocked_reason'])
        self.assertEqual(1, len(self.service.ticket_detail(self.customer, tid)['messages']))

    def test_model_fallback_respects_human_priority_and_manual_suggestions(self):
        model = Mock()
        model.classify.side_effect = GenerationError('unavailable')
        self.service.workflow.model = model
        tid = self.create()
        self.service.run_due_jobs()
        self.service.human_reply(self.staff, tid, {'content': '我来核查'})
        self.followup(tid)
        self.assertEqual(0, self.service.run_due_jobs())
        self.due()
        self.assertEqual('draft', self.last_run(tid)['state'])
        self.assertIn('15 分钟', self.last_run(tid)['blocked_reason'])
        self.assertEqual('customer', self.service.ticket_detail(self.customer, tid)['messages'][-1]['role'])
        self.service.ticket_action(self.staff, tid, {'action': 'resume'})
        self.service.ticket_action(self.staff, tid, {'action': 'rerun'})
        self.service.run_due_jobs()
        self.assertEqual('draft', self.last_run(tid)['state'])
        self.assertIn('人工请求', self.last_run(tid)['blocked_reason'])

    def test_model_failure_cannot_bypass_a_switch_changed_during_generation(self):
        model = Mock()
        def disable_and_fail(*args):
            self.console.settings(self.admin, {'reply_mode': 'review'})
            raise GenerationError('unavailable')
        model.classify.side_effect = disable_and_fail
        self.service.workflow.model = model
        tid = self.create()
        self.service.run_due_jobs()
        self.assertEqual('customer', self.service.ticket_detail(self.customer, tid)['messages'][-1]['role'])
        self.assertIsNone(self.last_run(tid))

    def test_only_human_followups_wait_one_minute_and_stay_private(self):
        tid = self.create()
        self.service.run_due_jobs()
        self.service.human_reply(self.staff, tid, {'content':'我来协助核对。'})
        self.assertFalse(self.db.one("SELECT id FROM generation_jobs WHERE state='queued'"))
        self.followup(tid)
        job = self.db.one("SELECT * FROM generation_jobs WHERE state='queued'")
        delay = datetime.fromisoformat(job['due_at'])-datetime.fromisoformat(job['created_at'])
        self.assertEqual(timedelta(seconds=60), delay)
        self.assertEqual(0, self.service.run_due_jobs())
        self.due()
        self.assertEqual('draft', self.last_run(tid)['state'])
        self.assertIn('15 分钟', self.last_run(tid)['blocked_reason'])
        private = self.service.ticket_detail(self.staff, tid)
        public = self.service.ticket_detail(self.customer, tid)
        self.assertIn('只给建议', private['human_notice'])
        self.assertEqual('customer', public['messages'][-1]['role'])
        self.assertNotIn('job', public)
        self.assertNotIn('draft_count', self.service.list_tickets(self.customer)[0])

    def test_timely_human_reply_cancels_pending_and_running_suggestion(self):
        tid = self.create()
        self.service.run_due_jobs()
        self.service.human_reply(self.staff, tid, {'content':'人工处理'})
        self.followup(tid)
        self.service.human_reply(self.staff, tid, {'content':'已看到你的新问题'})
        self.due()
        self.assertFalse(self.db.one("SELECT id FROM runs WHERE state='draft'"))
        self.followup(tid)
        original = self.service.workflow.build
        def human_during_build(*args):
            result = original(*args)
            self.service.human_reply(self.staff, tid, {'content':'人工已回答，请不要插话'})
            return result
        with patch.object(self.service.workflow, 'build', side_effect=human_during_build):
            self.due()
        self.assertEqual('human', self.service.ticket_detail(self.customer, tid)['messages'][-1]['role'])
        self.assertFalse(self.db.one("SELECT id FROM runs WHERE state='draft'"))

    def test_later_customer_message_restarts_wait_and_invalidates_suggestion(self):
        tid = self.create()
        self.service.run_due_jobs()
        self.service.human_reply(self.staff, tid, {'content':'人工处理'})
        self.followup(tid)
        first = self.db.one("SELECT * FROM generation_jobs WHERE state='queued'")
        self.followup(tid, '还有发票问题')
        self.assertEqual('cancelled', self.db.one('SELECT state FROM generation_jobs WHERE id=?',(first['id'],))['state'])
        self.due()
        old = self.last_run(tid)
        self.followup(tid, '新的错误是401')
        with self.assertRaises(DeskError):
            self.service.publish(self.staff, old['id'], {})

    def test_cooldown_boundary_and_explicit_takeover(self):
        tid = self.create()
        self.service.run_due_jobs()
        self.service.human_reply(self.staff, tid, {'content':'人工处理'})
        self.db.execute('UPDATE tickets SET human_until=? WHERE id=?', (after(seconds=-1), tid))
        self.followup(tid)
        self.service.run_due_jobs()
        self.assertEqual('sent', self.last_run(tid)['state'])
        self.service.ticket_action(self.staff, tid, {'action':'takeover'})
        self.db.execute('UPDATE tickets SET human_until=? WHERE id=?', (after(minutes=-20), tid))
        self.followup(tid)
        self.due()
        self.assertEqual('draft', self.last_run(tid)['state'])
        self.service.ticket_action(self.staff, tid, {'action':'resume'})
        self.followup(tid)
        self.service.run_due_jobs()
        self.assertEqual('sent', self.last_run(tid)['state'])

    def test_staff_can_send_suggestion_and_retract_ai_with_public_tombstone(self):
        tid = self.create()
        self.service.run_due_jobs()
        self.service.human_reply(self.staff, tid, {'content':'人工处理'})
        self.followup(tid)
        self.due()
        run = self.last_run(tid)
        self.service.publish(self.staff, run['id'], {})
        message = self.service.ticket_detail(self.customer, tid)['messages'][-1]
        self.assertEqual('assistant', message['role'])
        self.service.retract(self.staff, message['id'])
        self.service.retract(self.admin, message['id'])
        detail = self.service.ticket_detail(self.customer, tid)
        self.assertEqual('已撤回', detail['messages'][-1]['content'])
        self.assertEqual('已撤回', self.service.list_tickets(self.customer)[0]['preview'])
        self.assertEqual(1, self.db.one("SELECT COUNT(*) AS n FROM events WHERE kind='ai_retracted'")['n'])
        self.assertEqual(message['content'], self.db.one('SELECT content FROM messages WHERE id=?',(message['id'],))['content'])
        self.denied(self.service.retract, self.customer, message['id'])

    def test_staff_can_approve_eligible_balance_but_cannot_administer_accounts(self):
        self.denied(self.console.settings, self.staff, {'reply_mode':'review'})
        self.denied(self.console.update_user, self.staff, 3, {'balance_units':100})
        self.denied(self.console.save_subscription, self.staff, 3, {})
        self.denied(self.console.create_user, self.staff, {})
        self.denied(self.console.refund, self.staff, 3, {'status':'approved'})
        alice = self.db.one('SELECT * FROM users WHERE id=2')
        tid = self.service.create_ticket(alice, {'subject':'负余额','content':'帮我回正余额'})['ticket']['id']
        self.service.run_due_jobs()
        self.service.publish(self.staff, self.last_run(tid)['id'], {'execute_actions':True})
        self.assertEqual(0, self.db.one('SELECT balance_units FROM users WHERE id=2')['balance_units'])

    def test_global_switch_cancels_unsent_auto_jobs_but_keeps_human_assistance(self):
        tid = self.create()
        self.console.settings(self.admin, {'reply_mode':'review'})
        self.service.run_due_jobs()
        self.assertIsNone(self.last_run(tid))
        self.assertEqual('waiting_human', self.service.ticket(self.customer, tid)['status'])
        another = self.create()
        self.assertIsNone(self.last_run(another))
        self.assertEqual(0, self.service.run_due_jobs())
        self.service.human_reply(self.staff, another, {'content':'人工处理'})
        self.followup(another)
        self.due()
        self.assertEqual('draft', self.last_run(another)['state'])
        self.console.settings(self.admin, {'reply_mode':'auto'})
        self.service.run_due_jobs()
        self.assertEqual('draft', self.last_run(another)['state'])

    def test_human_takeover_global_switch_and_new_messages_win_inflight_races(self):
        for action in ('takeover','switch','new_message','resolve'):
            with self.subTest(action=action):
                self.console.settings(self.admin, {'reply_mode':'auto'})
                tid = self.create()
                original = self.service.workflow.build
                def intervene(*args):
                    result = original(*args)
                    if action in {'takeover','resolve'}:
                        self.service.ticket_action(self.staff, tid, {'action':action})
                    elif action == 'switch':
                        self.console.settings(self.admin, {'reply_mode':'review'})
                    else:
                        self.followup(tid, '新的问题是退款')
                    return result
                with patch.object(self.service.workflow, 'build', side_effect=intervene):
                    self.service.run_due_jobs(limit=1)
                self.assertFalse(self.db.one("SELECT id FROM messages WHERE ticket_id=? AND role='assistant'", (tid,)))
                self.service.ticket_action(self.staff, tid, {'action':'resolve'})

    def test_network_work_does_not_hold_database_lock(self):
        tid = self.create()
        entered, release, read_done = threading.Event(), threading.Event(), threading.Event()
        original = self.service.workflow.build
        def slow(*args):
            entered.set()
            release.wait(5)
            return original(*args)
        with patch.object(self.service.workflow,'build',side_effect=slow):
            worker = threading.Thread(target=self.service.run_due_jobs)
            worker.start()
            self.assertTrue(entered.wait(2))
            reader = threading.Thread(target=lambda:(self.service.ticket_detail(self.customer, tid),read_done.set()))
            reader.start()
            try:
                self.assertTrue(read_done.wait(1), 'slow model blocked live page reads')
            finally:
                release.set(); worker.join(3); reader.join(3)

    def test_failed_job_transfers_to_human_without_leaking_provider_error(self):
        tid = self.create()
        with patch.object(self.service.workflow,'build',side_effect=RuntimeError('secret_key=private-value')):
            self.service.run_due_jobs()
        detail = self.service.ticket_detail(self.staff, tid)
        self.assertEqual('waiting_human', detail['ticket']['status'])
        self.assertEqual('idle', detail['reply_state'])
        self.assertNotIn('private-value', json.dumps(detail))

    def test_view_switch_is_session_scoped_and_personal_owner_scoped(self):
        for email in ('admin@lumen.test','support1@lumen.test','support2@lumen.test'):
            result, token = self.service.login(email,'Demo123!')
            user = self.service.authenticate(token)
            self.assertEqual('workspace', user['view_mode'])
            _, other_token = self.service.login(email,'Demo123!')
            self.service.switch_view(user,'personal')
            personal = self.service.authenticate(token)
            self.assertEqual('personal',personal['view_mode'])
            self.assertEqual('workspace',self.service.authenticate(other_token)['view_mode'])
            self.denied(self.app.dispatch, 'GET','/api/staff/dashboard',personal,{})
            self.denied(self.app.dispatch, 'GET','/api/admin/users',personal,{})
            ticket = self.service.create_ticket(personal, {'subject':'我自己的工单','content':'怎么配置客户端','user_id':2})
            self.assertEqual(personal['id'],ticket['ticket']['user_id'])
            self.assertNotIn('runs',ticket)
            self.assertTrue(all(t['user_id']==personal['id'] for t in self.service.list_tickets(personal)))
            simulate_request(self.db, personal, {'model':'gpt-6.1-sol'})
            self.service.switch_view(personal,'workspace')
            self.assertEqual('workspace',self.service.authenticate(token)['view_mode'])
        personal, _ = self.service.login('ben@lumen.test','Demo123!')
        self.denied(self.service.switch_view,{**self.customer,'csrf':personal['csrf']},'workspace')

    def test_plans_and_balance_are_current_in_customer_and_tool_views(self):
        plan = {'name':'进阶月卡','quota_units':900000,'used_units':0,'reset_at':after(days=7),'expires_at':after(days=30)}
        account = self.console.save_subscription(self.admin,3,plan)
        current = account['subscriptions'][0]
        self.assertEqual('进阶月卡', current['name'])
        self.assertEqual(1,sum(s['status']=='active' for s in account['subscriptions']))
        self.console.save_subscription(self.admin,3,{'name':'升级月卡','quota_units':1200000},current['id'])
        self.console.update_user(self.admin,3,{'balance_units':550000})
        public = self.service.account(self.customer)
        self.assertEqual('升级月卡',public['subscriptions'][0]['name'])
        self.assertEqual(550000,public['user']['balance_units'])
        result = simulate_request(self.db,self.customer,{'model':'gpt-6.1-sol'})
        self.assertEqual(200,result['status_code'])
        self.assertEqual(1200,self.service.account(self.customer)['subscriptions'][0]['used_units'])
        tid = self.create('我的套餐叫什么，剩余多少额度？')
        self.service.run_due_jobs()
        self.assertIn('升级月卡',self.last_run(tid)['answer'])
        with self.assertRaises(DeskError):
            self.console.save_subscription(self.admin,4,plan,current['id'])

    def test_revision_only_notifies_successful_commits(self):
        before=self.db.revision
        with self.assertRaises(RuntimeError):
            with self.db.transaction():
                self.db.execute("UPDATE users SET name='rollback' WHERE id=3")
                raise RuntimeError()
        self.assertEqual(before,self.db.revision)
        with self.db.transaction():
            self.db.execute("UPDATE users SET name='committed' WHERE id=3")
            self.db.event(None,'test','commit')
        self.assertEqual(before+1,self.db.revision)
        self.assertEqual('committed',self.service.account(self.customer)['user']['name'])

    def test_sse_stream_emits_changes_without_private_payload(self):
        _, token=self.service.login('ben@lumen.test','Demo123!')
        app=self.app
        class Socket:
            def __init__(self):
                self.output=bytearray()
                self.input=io.BytesIO(f'GET /api/events HTTP/1.1\r\nHost: localhost\r\nCookie: lumen_session={token}\r\n\r\n'.encode())
                self.frames=0
            def makefile(self,*args):return self.input
            def sendall(inner,value):
                inner.output.extend(value)
                if value.startswith(b'id:'):
                    inner.frames+=1
                    if inner.frames==1:self.db.set_setting('test_revision',True)
                    else:app.stopped.set()
        sock=Socket();handler=make_handler(app);handler.log_message=lambda *args:None
        handler(sock,('127.0.0.1',1),SimpleNamespace(server_name='localhost',server_port=80))
        output=bytes(sock.output).decode()
        self.assertIn('text/event-stream',output)
        self.assertEqual(2,sock.frames)
        self.assertNotIn(token,output)
        self.assertNotIn('test_revision',output)
        self.assertNotIn('ben@',output)


class MigrationTests(unittest.TestCase):
    def test_old_database_preserves_accounts_tickets_sessions_and_finances(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.db'
            old=sqlite3.connect(path)
            old.executescript(SCHEMA.replace("'admin','support','personal'","'admin','personal'").replace(", view_mode TEXT NOT NULL DEFAULT 'workspace'",""))
            old.execute("INSERT INTO users VALUES (1,'legacy@lumen.test','旧账号',?,'personal','active',3456,'','',?)",(password_hash('Demo123!'),now()))
            old.execute("INSERT INTO tickets(user_id,subject,created_at,updated_at) VALUES (1,'原工单',?,?)",(now(),now()))
            old.execute("INSERT INTO messages(ticket_id,author_id,role,content,created_at) VALUES (1,1,'customer','原消息',?)",(now(),))
            old.execute("INSERT INTO sessions VALUES (?,?,?,?)",(hashlib.sha256(b'old-token').hexdigest(),1,'legacy-csrf',after(hours=1)))
            old.execute("INSERT INTO settings VALUES ('reply_mode','\"review\"')")
            old.commit();old.close()
            db=Database(path)
            self.assertEqual(3456,db.one('SELECT * FROM users WHERE id=1')['balance_units'])
            self.assertEqual('原消息',db.one('SELECT * FROM messages')['content'])
            self.assertEqual([],db.all('PRAGMA foreign_key_check'))
            self.assertEqual(2,db.one("SELECT COUNT(*) AS n FROM users WHERE role='support'")['n'])
            self.assertEqual('auto',db.settings()['reply_mode'])
            self.assertEqual(15,db.settings()['human_cooldown_minutes'])
            self.assertTrue(db.one('SELECT * FROM sessions WHERE csrf=?',('legacy-csrf',)))
            db.set_setting('reply_mode','review');db.close()
            db=Database(path)
            self.assertEqual('review',db.settings()['reply_mode'])
            self.assertEqual(2,db.one("SELECT COUNT(*) AS n FROM users WHERE role='support'")['n'])
            db.close()


if __name__=='__main__':unittest.main()

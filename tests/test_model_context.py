"""Transport diagnostics, model provenance and customer/human conversation replay."""
import contextlib
import io
import json
import os
import ssl
import sys
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support_agent.desk.config import PortalConfig
from support_agent.desk.engine import local_intents, quality_check
from support_agent.desk.model import DeskModel
from support_agent.desk.service import DeskService
from support_agent.desk.storage import Database, after
from support_agent.portal import serve
from support_agent.providers import GenerationError, ResponsesProvider, model_ssl_context


class ContextProvider(ResponsesProvider):
    def __init__(self):
        super().__init__('test-secret-key-only', 'gpt-6-astra')
        self.requests = []

    def _request(self, payload):
        data = json.loads(payload['input'])
        self.requests.append((payload['text']['format']['name'], data, payload))
        stage = payload['text']['format']['name']
        if stage == 'support_intents':
            result = {'intents': local_intents(data['message'], {})}
        elif stage == 'support_reply':
            result = {'evidence_summary': '依据本次业务查询回复。', 'answer': '我已了解你的反馈。' + data['baseline_answer']}
        else:
            result = {'issues': []}
        return {'model': 'gpt-6-astra-test-snapshot', 'output_text': json.dumps(result, ensure_ascii=False),
                'usage': {'input_tokens': 123, 'output_tokens': 45, 'total_tokens': 168}}


class ModelTransportTests(unittest.TestCase):
    def test_certifi_roots_are_loaded_without_disabling_tls_checks(self):
        with patch.dict(os.environ, {}, clear=True):
            context = model_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        context = Mock()
        with patch.dict(os.environ, {}, clear=True), patch('ssl.create_default_context', return_value=context), patch.dict(sys.modules, {'certifi': SimpleNamespace(where=lambda: '/trusted/roots.pem')}):
            self.assertIs(context, model_ssl_context())
        context.load_verify_locations.assert_called_once_with(cafile='/trusted/roots.pem')

    def test_explicit_ca_configuration_is_preserved(self):
        context = Mock()
        with patch.dict(os.environ, {'SSL_CERT_FILE': '/custom/root.pem'}, clear=True), patch('ssl.create_default_context', return_value=context):
            model_ssl_context()
        context.load_verify_locations.assert_not_called()

    def test_tls_timeout_and_http_failures_have_safe_diagnostics(self):
        errors = [(urllib.error.URLError(ssl.SSLCertVerificationError('private-key-should-not-leak')), 'tls_certificate'),
                  (TimeoutError('private-key-should-not-leak'), 'timeout'),
                  (urllib.error.HTTPError('https://private.example', 401, 'private-key-should-not-leak', {}, io.BytesIO(b'private-key-should-not-leak')), 'http')]
        for error, code in errors:
            model = DeskModel(ResponsesProvider('test-secret-key-only', 'gpt-6-astra'))
            with self.subTest(code=code), patch('urllib.request.urlopen', side_effect=error), self.assertRaises(GenerationError):
                model.classify('hello', {})
            report = model.trace[-1]
            self.assertFalse(report['ok'])
            self.assertEqual(code, report['error']['code'])
            self.assertNotIn('private-key-should-not-leak', json.dumps(report))
            self.assertNotIn('https://', json.dumps(report))
            if code == 'http':
                self.assertEqual(401, report['error']['http_status'])

    def test_incomplete_output_gets_one_bounded_retry(self):
        provider = ResponsesProvider('test-key', 'gpt-6-astra')
        outputs = [{'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}},
                   {'output_text': '{"intents":["technical"]}', 'model': 'gpt-6-astra'}]
        budgets = []
        def respond(payload):
            budgets.append(payload['max_output_tokens'])
            return outputs.pop(0)
        model = DeskModel(provider)
        with patch.object(provider, '_request', side_effect=respond):
            self.assertEqual(['technical'], model.classify('503', {}))
        self.assertEqual([4096, 8192], budgets)
        self.assertEqual([False, True], [c['ok'] for c in model.trace])

    def test_invalid_schema_records_failure_without_raw_output(self):
        provider = ResponsesProvider('private-key', 'gpt-6-astra')
        model = DeskModel(provider)
        with patch.object(provider, '_request', return_value={'output_text': '{"intents":"private-key"}'}), self.assertRaises(GenerationError):
            model.classify('hello', {})
        self.assertEqual('invalid_json', model.trace[-1]['error']['code'])
        self.assertNotIn('private-key', json.dumps(model.trace))

    def test_selected_model_is_checked_before_database_or_server_creation(self):
        with patch('support_agent.portal.check_model', side_effect=GenerationError('TLS failed', code='tls_certificate')), patch('support_agent.portal.Database') as database, patch('support_agent.portal.ThreadingHTTPServer') as server, self.assertRaises(GenerationError):
            serve(PortalConfig(provider='openai', api_key='private-key', model='gpt-6-astra'))
        database.assert_not_called()
        server.assert_not_called()


class ConversationContextTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(':memory:')
        self.addCleanup(self.db.close)
        self.provider = ContextProvider()
        self.service = DeskService(self.db, DeskModel(self.provider), seed_tickets=False)
        self.customer, self.staff = [self.db.one('SELECT * FROM users WHERE id=?', (i,)) for i in (3, 5)]

    def create(self, text='Claude Code 使用 claude-opus-4-8 报错503，失败请求扣费了吗？'):
        return self.service.create_ticket(self.customer, {'subject': '503排障', 'content': text})['ticket']['id']

    def last(self, tid):
        return self.service.ticket_detail(self.db.one('SELECT * FROM users WHERE id=1'), tid)['runs'][0]

    def due(self):
        self.db.execute("UPDATE generation_jobs SET due_at=? WHERE state='queued'", (after(seconds=-1),))
        self.service.run_due_jobs()

    def test_actual_reply_has_model_name_trace_and_no_fake_human_cooldown(self):
        tid = self.create()
        detail = self.service.ticket_detail(self.customer, tid)
        run = self.last(tid)
        self.assertEqual('sent', run['state'])
        self.assertEqual('openai', run['provider'])
        self.assertEqual('model', detail['messages'][-1]['reply_source'])
        self.assertEqual('gpt-6-astra-test-snapshot', detail['messages'][-1]['reply_model'])
        self.assertIsNone(detail['ticket']['human_until'])
        self.assertTrue(all(c['ok'] for c in run['quality']['model']['calls']))
        self.assertEqual('gpt-6-astra', run['quality']['model']['requested_model'])
        self.assertNotIn('test-secret-key-only', json.dumps(detail) + json.dumps(run))
        self.assertEqual('verified', self.service.model_status['status'])

    def test_all_stages_receive_customer_ai_and_human_messages(self):
        tid = self.create()
        self.service.human_reply(self.staff, tid, {'content': '请切换线路后重试；这次我继续跟进。'})
        self.service.customer_message(self.customer, tid, {'content': '我照客服说的切换线路了，还是报错503。'})
        self.due()
        stages = self.provider.requests[-3:]
        for name, data, payload in stages:
            history = data['history'] if name == 'support_intents' else data['conversation_context']
            self.assertEqual(['customer', 'ai', 'human'], [m['speaker'] for m in history['conversation']])
            self.assertIn('切换线路', history['conversation'][-1]['content'])
            self.assertTrue(history['human_priority'])
        run = self.last(tid)
        self.assertEqual('draft', run['state'])
        self.assertTrue(run['quality']['model']['includes_human'])
        self.assertIn('不重复', run['answer'])

    def test_uncertain_recovery_is_acknowledged_then_explicit_confirmation_closes(self):
        tid = self.create()
        self.service.customer_message(self.customer, tid, {'content': '好的，我刚刚看错了。不好意思，现在应该好了'})
        run = self.last(tid)
        self.assertEqual(['resolution_check'], run['intents'])
        self.assertEqual('sent', run['state'])
        self.assertIn('确认', run['answer'])
        self.assertNotIn('完整错误文字', run['answer'])
        self.assertNotEqual('resolved', self.service.ticket(self.customer, tid)['status'])
        self.service.customer_message(self.customer, tid, {'content': '确认，已经可以用了，谢谢你！'})
        self.assertEqual('resolved', self.service.ticket(self.customer, tid)['status'])
        self.assertEqual('openai', self.last(tid)['provider'])

    def test_negative_or_new_problem_is_not_closed(self):
        for text in ['还没有解决', '现在应该好了？', '现在可以用了，但是还有退款问题', '还是报错，没有恢复']:
            self.assertNotEqual(['resolved'], local_intents(text, {}), text)

    def test_retracted_messages_private_drafts_secrets_and_other_users_are_excluded(self):
        tid = self.create()
        message = self.service.ticket_detail(self.customer, tid)['messages'][-1]
        self.service.retract(self.staff, message['id'])
        self.db.execute("UPDATE messages SET content='withdrawn-sensitive-text' WHERE id=?", (message['id'],))
        other = self.db.one('SELECT * FROM users WHERE id=4')
        self.service.create_ticket(other, {'subject':'private', 'content':'other-customer-private-text'})
        self.service.human_reply(self.staff, tid, {'content': '请不要发送 api_key=abcdefghijklmnopqrstuv'})
        self.service.customer_message(self.customer, tid, {'content': '还是报错503'})
        self.due()
        run = self.last(tid)
        self.db.execute("UPDATE runs SET answer='internal-draft-private-text' WHERE id=?", (run['id'],))
        self.service.customer_message(self.customer, tid, {'content': '又试了一次，还是503'})
        self.due()
        data = json.dumps([r[1] for r in self.provider.requests[-3:]], ensure_ascii=False)
        for excluded in ['withdrawn-sensitive-text','other-customer-private-text','internal-draft-private-text','abcdefghijklmnopqrstuv']:
            self.assertNotIn(excluded, data)
        self.assertIn('已撤回', data)
        self.assertIn('已隐藏', data)

    def test_long_history_is_bounded_and_marked(self):
        tid = self.create()
        for _ in range(30):
            self.db.execute("INSERT INTO messages(ticket_id,role,content,created_at) VALUES (?,'customer',?,?)", (tid, '长消息'*1000, after()))
        self.service.customer_message(self.customer, tid, {'content': '再查询一次503'})
        history = self.provider.requests[-3][1]['history']
        self.assertTrue(history['history_truncated'])
        self.assertLessEqual(len(history['conversation']), 24)
        self.assertLess(sum(len(m['content']) for m in history['conversation']), 16100)

    def test_model_version_digits_do_not_reject_an_evidence_grounded_reply(self):
        self.assertTrue(quality_check('claude-opus-4-8：失败费用 $0.0000。', '失败费用 $0.0000。')['passed'])
        self.assertFalse(quality_check('claude-opus-4-8：已扣费 $503。', '失败费用 $0.0000。')['passed'])

    def test_review_receives_the_same_business_evidence_and_current_question(self):
        tid = self.create()
        stages = {name: data for name, data, _ in self.provider.requests}
        reply, review = stages['support_reply'], stages['support_quality']
        self.assertEqual(reply['approved_facts'], review['approved_facts'])
        self.assertEqual(reply['message'], review['message'])
        self.assertIn('check_platform_status', [t['name'] for t in review['approved_facts']])
        self.assertTrue(self.last(tid)['quality']['model']['review']['passed'])

    def test_model_can_revise_a_rejected_draft_once_and_send_the_verified_result(self):
        original_request = self.provider._request
        def respond(payload):
            data = json.loads(payload['input'])
            if payload['text']['format']['name'] == 'support_reply' and not data['revision_feedback']:
                original_request(payload)
                return {'output_text': json.dumps({'evidence_summary': '依据本次业务查询回复。', 'answer': '已扣费 $9999。'})}
            return original_request(payload)
        with patch.object(self.provider, '_request', side_effect=respond):
            tid = self.create()
        run = self.last(tid)
        self.assertEqual('sent', run['state'])
        self.assertEqual('openai', run['provider'])
        self.assertFalse(run['quality']['model_fallback'])
        self.assertTrue(run['quality']['revision_attempted'])
        self.assertTrue(run['quality']['revised'])
        self.assertNotIn('9999', run['answer'])
        self.assertEqual(5, len(run['quality']['model']['calls']))
        revision = [d for name, d, _ in self.provider.requests if name == 'support_reply'][-1]
        self.assertTrue(revision['revision_feedback'])
        self.assertEqual('已扣费 $9999。', revision['previous_answer'])

    def test_failed_revision_explains_review_rejection_without_leaking_credentials(self):
        self.provider.api_base = 'https://private.example/v1'
        original_request = self.provider._request
        def respond(payload):
            if payload['text']['format']['name'] == 'support_quality':
                original_request(payload)
                return {'output_text': json.dumps({'issues': [
                    '事实冲突，请核对余额。 test-secret-key-only https://private.example/v1 support@example.test'
                ]})}
            return original_request(payload)
        with patch.object(self.provider, '_request', side_effect=respond):
            tid = self.create()
        run = self.last(tid)
        self.assertEqual('local', run['provider'])
        self.assertTrue(run['quality']['revision_attempted'])
        self.assertTrue(run['quality']['model_fallback'])
        self.assertEqual(5, len(run['quality']['model']['calls']))
        self.assertIn('事实冲突', ' '.join(run['quality']['warnings']))
        self.assertFalse(run['quality']['model']['review']['passed'])
        report = json.dumps(run['quality'], ensure_ascii=False)
        for secret in ['test-secret-key-only', 'private.example', 'support@example.test']:
            self.assertNotIn(secret, report)


if __name__ == '__main__':
    unittest.main()

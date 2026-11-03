"""Wire protocol checks for custom model endpoints with no live API credentials."""

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from support_agent.desk.model import DeskModel
from support_agent.providers import ChatCompletionsProvider, GenerationError, ResponsesProvider


def response(data):
    return io.BytesIO(json.dumps(data).encode("utf-8"))


class ModelConnectionTests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_responses_custom_endpoint_key_model_and_schema(self, urlopen):
        urlopen.return_value = response({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"intents":["quota","refund"]}'}]}]})
        provider = ResponsesProvider("test-private-key", "vendor/custom-model", "https://gateway.example/prefix/")
        self.assertEqual(DeskModel(provider).classify("额度用完了，我想退款", []), ["quota", "refund"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://gateway.example/prefix/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-private-key")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "vendor/custom-model")
        self.assertFalse(body["store"])
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertNotIn("messages", body)

    @patch("urllib.request.urlopen")
    def test_chat_custom_endpoint_translates_prompt_and_strict_schema(self, urlopen):
        urlopen.return_value = response({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": '{"intents":["quota"]}'}}]})
        provider = ChatCompletionsProvider("test-private-key", "vendor/custom-model", "http://localhost:9000/v1")
        self.assertEqual(DeskModel(provider).classify("额度还剩多少？", []), ["quota"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:9000/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-private-key")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "vendor/custom-model")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(json.loads(body["messages"][1]["content"])["message"], "额度还剩多少？")
        self.assertFalse(body["store"])
        self.assertEqual(body["max_completion_tokens"], 4096)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertFalse(body["response_format"]["json_schema"]["schema"]["additionalProperties"])
        self.assertNotIn("text", body)
        self.assertNotIn("max_output_tokens", body)

    def test_malformed_or_truncated_outputs_become_generation_errors(self):
        cases = [(ResponsesProvider, {"output": None}), (ResponsesProvider, {"output": [1]}),
                 (ResponsesProvider, {"status": "incomplete", "output_text": '{"ok":true}'}),
                 (ChatCompletionsProvider, {"choices": None}), (ChatCompletionsProvider, {"choices": [None]}),
                 (ChatCompletionsProvider, {"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "length"}]}),
                 (ChatCompletionsProvider, {"choices": [{"message": {"content": "no", "refusal": "refused"}}]})]
        for provider_class, data in cases:
            with self.subTest(data=data), self.assertRaises(GenerationError):
                provider_class._output_text(data)

    @patch("urllib.request.urlopen")
    def test_http_errors_do_not_echo_upstream_secrets(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("https://gateway.example", 401, "test-private-key", {}, io.BytesIO(b"test-private-key"))
        with self.assertRaises(GenerationError) as caught:
            DeskModel(ResponsesProvider("test-private-key", "model")).classify("hello", [])
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn("test-private-key", str(caught.exception))

    @patch("urllib.request.urlopen")
    def test_invalid_json_root_becomes_generation_error(self, urlopen):
        for data in [[], None, "test-private-key"]:
            urlopen.return_value = response(data)
            with self.subTest(data=data), self.assertRaises(GenerationError):
                DeskModel(ResponsesProvider("test-private-key", "model")).classify("hello", [])


if __name__ == "__main__":
    unittest.main()

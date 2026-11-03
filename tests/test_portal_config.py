"""Temporary terminal configuration: privacy, validation, and both launch paths."""

import contextlib
import getpass
import io
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from scripts import start_demo
from support_agent.desk.config import argument_parser, config_from_args
from support_agent.portal import main
from support_agent.providers import GenerationError


MODEL_ENV = {
    "SUPPORT_AGENT_PROVIDER": "openai",
    "OPENAI_API_KEY": "test-private-key",
    "OPENAI_MODEL": "vendor/custom-model",
    "OPENAI_BASE_URL": "https://gateway.example/api/v1/",
    "OPENAI_API_MODE": "chat_completions",
}


class PortalConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def config(self, argv=(), environ=None, *, interactive=False):
        return config_from_args(argument_parser().parse_args(argv), root=self.root,
                                environ={} if environ is None else environ, interactive=interactive)

    def test_first_run_is_offline_without_prompts(self):
        with patch("builtins.input") as prompt, patch("getpass.getpass") as key:
            config = self.config(interactive=True)
        prompt.assert_not_called()
        key.assert_not_called()
        self.assertEqual(config.database, self.root / "runtime/lumen_desk.db")
        self.assertIsNone(config.model_provider())

    def test_existing_dotenv_is_not_read_even_if_malformed(self):
        path = self.root / ".env"
        contents = 'OPENAI_API_KEY="old-key\nSUPPORT_AGENT_PROVIDER=openai'
        path.write_text(contents)
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read configuration files")):
            config = self.config()
        self.assertEqual(config.provider, "local")
        self.assertEqual(path.read_text(), contents)
        with self.assertRaisesRegex(ValueError, "缺少模型连接配置"):
            self.config(["--provider", "openai"])

    def test_environment_configuration_is_reused_without_prompting(self):
        with patch("builtins.input") as prompt, patch("getpass.getpass") as key:
            config = self.config(environ=MODEL_ENV, interactive=True)
        prompt.assert_not_called()
        key.assert_not_called()
        provider = config.model_provider()
        self.assertEqual(provider.api_base, "https://gateway.example/api/v1")
        self.assertEqual(provider.api_key, "test-private-key")
        self.assertEqual(provider.model, "vendor/custom-model")
        self.assertEqual(provider.api_mode, "chat_completions")
        self.assertNotIn("test-private-key", repr(config) + repr(provider))

    def test_cli_overrides_current_environment(self):
        config = self.config(["--model", "cli-model", "--base-url", "http://localhost:9000/v1",
                              "--api-mode", "responses", "--port", "8099"], MODEL_ENV)
        self.assertEqual(config.model, "cli-model")
        self.assertEqual(config.api_key, "test-private-key")
        self.assertEqual(config.api_mode, "responses")
        self.assertEqual(config.base_url, "http://localhost:9000/v1")
        self.assertEqual(config.port, 8099)

    def test_forced_local_ignores_invalid_model_settings(self):
        env = {**MODEL_ENV, "OPENAI_API_KEY": "not\na-key", "OPENAI_BASE_URL": "invalid", "OPENAI_API_MODE": "wrong"}
        with patch("builtins.input") as prompt, patch("getpass.getpass") as key:
            config = self.config(["--provider", "local"], env, interactive=True)
        prompt.assert_not_called()
        key.assert_not_called()
        self.assertEqual(config.api_key, "")
        self.assertIsNone(config.model_provider())

    def test_interactive_setup_collects_missing_values_without_persisting(self):
        env = {}
        with patch.dict(os.environ, {}, clear=True), patch("builtins.input", side_effect=[
            "https://gateway.example/custom/v1/", "vendor/model-kept", "1"
        ]), patch("getpass.getpass", return_value="temporary-private-key") as key, contextlib.redirect_stdout(io.StringIO()) as output:
            config = self.config(["--provider", "openai"], env, interactive=True)
            self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertNotIn("OPENAI_BASE_URL", os.environ)
        key.assert_called_once()
        self.assertEqual(config.api_key, "temporary-private-key")
        self.assertEqual(config.base_url, "https://gateway.example/custom/v1")
        self.assertEqual(config.model, "vendor/model-kept")
        self.assertEqual(config.api_mode, "chat_completions")
        self.assertEqual(env, {})
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertNotIn(config.api_key, output.getvalue())

    def test_only_missing_fields_are_requested(self):
        env = {k: v for k, v in MODEL_ENV.items() if k != "OPENAI_API_KEY"}
        with patch("builtins.input") as prompt, patch("getpass.getpass", return_value="new-key") as key, contextlib.redirect_stdout(io.StringIO()):
            config = self.config(environ=env, interactive=True)
        prompt.assert_not_called()
        key.assert_called_once()
        self.assertEqual(config.api_key, "new-key")
        self.assertEqual(config.model, MODEL_ENV["OPENAI_MODEL"])

    def test_interactive_defaults_and_validation_retry(self):
        with patch("builtins.input", side_effect=[
            "https://host/v1/chat/completions", "", "", "vendor/model", "wrong", ""
        ]), patch("getpass.getpass", side_effect=["", "key-with-newline\ninvalid", "valid-key"]), contextlib.redirect_stdout(io.StringIO()) as output:
            config = self.config(["--provider", "openai"], interactive=True)
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.model, "vendor/model")
        self.assertEqual(config.api_mode, "responses")
        self.assertNotIn("key-with-newline", output.getvalue())
        self.assertNotIn("valid-key", output.getvalue())

    def test_each_launch_and_each_project_prompts_again(self):
        with patch("builtins.input", side_effect=["https://host/v1", "model", "1"] * 3) as prompt, patch("getpass.getpass", return_value="transient-key") as key, contextlib.redirect_stdout(io.StringIO()):
            self.config(["--provider", "openai"], interactive=True)
            self.config(["--provider", "openai"], interactive=True)
            other = self.root / "other-project"
            other.mkdir()
            config_from_args(argument_parser().parse_args(["--provider", "openai"]), root=other, environ={}, interactive=True)
        self.assertEqual(key.call_count, 3)
        self.assertEqual(prompt.call_count, 9)
        self.assertEqual(list(self.root.rglob("*")), [self.root / "other-project"])

    def test_no_input_mode_never_reads_stdin(self):
        with patch("builtins.input") as prompt, patch("getpass.getpass") as key, self.assertRaisesRegex(ValueError, "缺少模型连接配置"):
            self.config(["--provider", "openai", "--no-input"], interactive=True)
        prompt.assert_not_called()
        key.assert_not_called()

    def test_missing_noninteractive_settings_give_next_step(self):
        with self.assertRaises(ValueError) as caught:
            self.config(["--provider", "openai"])
        for text in ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL", "交互终端", "--provider local"]:
            self.assertIn(text, str(caught.exception))

    def test_getpass_does_not_fall_back_to_echoed_input(self):
        def insecure_terminal(*_):
            warnings.warn("cannot disable echo", getpass.GetPassWarning)
            raise AssertionError("must abort before fallback input")
        env = {k: v for k, v in MODEL_ENV.items() if k != "OPENAI_API_KEY"}
        with patch("getpass.getpass", side_effect=insecure_terminal), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "无法隐藏密钥输入"):
            self.config(environ=env, interactive=True)

    def test_invalid_supplied_urls_and_full_endpoints_fail_without_echo(self):
        for url in ["ftp://host/v1", "https://user:secret@host/v1", "https://host/v1?key=secret",
                    "https://host/v1#secret", "https://host/v1/responses", "https://host/v1/chat/completions",
                    "https://host:invalid/v1", "https://host:0/v1", "https://host/a b", "https://[bad"]:
            with self.subTest(url=url), self.assertRaises(ValueError) as caught:
                self.config(["--base-url", url], MODEL_ENV)
            self.assertNotIn("secret", str(caught.exception))

    def test_invalid_environment_values_fail_without_tracebacks(self):
        for override in [{"SUPPORT_WEB_PORT": "abc"}, {"SUPPORT_WEB_PORT": "65536"},
                         {"SUPPORT_AGENT_PROVIDER": "typo"}, {"OPENAI_API_MODE": "typo"},
                         {"OPENAI_API_KEY": "key\nheader"}, {"OPENAI_API_KEY": "你的密钥"}]:
            with self.subTest(env=override), self.assertRaises(ValueError):
                self.config(environ={**MODEL_ENV, **override})

    def test_database_setting_still_respects_project_root(self):
        config = self.config(environ={"SUPPORT_WEB_PORT": "8090", "SUPPORT_DESK_DB": "runtime/another.db"})
        self.assertEqual(config.port, 8090)
        self.assertEqual(config.database, self.root / "runtime/another.db")

    def test_launcher_preserves_flags_and_reads_existing_environment(self):
        with patch.object(start_demo, "PROJECT", self.root), patch.dict(os.environ, MODEL_ENV, clear=True), patch("support_agent.portal.serve") as serve:
            start_demo.main(["--no-browser", "--model", "cli-model", "--base-url", "http://localhost:9000/custom", "--api-mode", "responses"])
        config = serve.call_args.args[0]
        self.assertEqual(config.api_key, "test-private-key")
        self.assertEqual(config.model, "cli-model")
        self.assertEqual(config.base_url, "http://localhost:9000/custom")
        self.assertEqual(config.api_mode, "responses")
        self.assertEqual(serve.call_args.kwargs, {"launcher": True, "open_browser": False})

    def test_both_entrypoints_accept_interactive_input(self):
        for launcher in [False, True]:
            with self.subTest(launcher=launcher), patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["http://localhost:9000/v1", "model-kept", "1"]), patch("getpass.getpass", return_value="temporary-key"), patch("support_agent.portal.serve") as serve, contextlib.redirect_stdout(io.StringIO()):
                main(["--provider", "openai"], root=self.root, launcher=launcher)
            self.assertEqual(serve.call_args.args[0].api_key, "temporary-key")
            self.assertEqual(serve.call_args.args[0].model, "model-kept")

    def test_redirected_stdin_fails_without_reading_or_starting(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=False), patch("builtins.input") as prompt, patch("getpass.getpass") as key, patch("support_agent.portal.serve") as serve, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["--provider", "openai"], root=self.root)
        self.assertEqual(caught.exception.code, 2)
        prompt.assert_not_called()
        key.assert_not_called()
        serve.assert_not_called()

    def test_cancel_and_eof_exit_cleanly_before_starting(self):
        for error in [KeyboardInterrupt(), EOFError()]:
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=error), patch("support_agent.portal.Database") as database, patch("support_agent.portal.serve") as serve, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as caught:
                main(["--provider", "openai"], root=self.root)
            self.assertEqual(caught.exception.code, 130)
            self.assertIn("已取消", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())
            database.assert_not_called()
            serve.assert_not_called()
            self.assertEqual(list(self.root.iterdir()), [])

    def test_connection_check_does_not_create_db_or_open_browser(self):
        def structured(name, instructions, data, properties):
            return {"intents": ["technical"]} if name == "support_intents" else {"answer": data["baseline_answer"]} if name == "support_reply" else {"issues": []}
        with patch.dict(os.environ, MODEL_ENV, clear=True), patch("support_agent.portal.Database") as database, patch("support_agent.portal.webbrowser.open") as browser, patch("support_agent.desk.model.DeskModel.structured", side_effect=structured) as request, contextlib.redirect_stdout(io.StringIO()) as output:
            main(["--check-model"], root=self.root)
        database.assert_not_called()
        browser.assert_not_called()
        self.assertEqual([c.args[0] for c in request.call_args_list], ["support_intents", "support_reply", "support_quality"])
        self.assertIn("未使用本地回退", output.getvalue())
        self.assertIn("vendor/custom-model", output.getvalue())
        self.assertNotIn("test-private-key", output.getvalue())

    def test_failed_connection_check_exits_nonzero(self):
        with patch.dict(os.environ, MODEL_ENV, clear=True), patch("support_agent.desk.model.DeskModel.structured", side_effect=GenerationError("TLS 校验失败", code="tls_certificate")), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            main(["--check-model"], root=self.root)
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

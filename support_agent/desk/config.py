"""Portal settings kept in process memory: CLI, environment, then terminal input."""

from __future__ import annotations

import argparse
import getpass
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ..providers import ChatCompletionsProvider, ResponsesProvider


def validate_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        url = urlsplit(value)
        valid = (url.scheme in {"http", "https"} and url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment and url.port != 0
                 and value.isascii() and not any(c.isspace() or ord(c) < 32 for c in value))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("API 地址应为 http(s) 地址前缀，不含用户名、密码、查询参数或片段")
    if url.path.endswith(("/responses", "/chat/completions")):
        raise ValueError("只填写 API 地址前缀，去掉末尾的 /responses 或 /chat/completions；程序会自动拼接")
    return value


def validate_key(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("API Key 不能为空；请粘贴服务商提供的密钥，再按 Enter")
    if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("API Key 格式无效；请填写实际密钥，不要填写提示文字或额外空格")
    return value


def validate_model(value: str) -> str:
    value = value.strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("模型 ID 不能为空或包含控制字符；请填写服务商提供的实际名称")
    return value


def validate_api_mode(value: str) -> str:
    if value not in {"responses", "chat_completions"}:
        raise ValueError("接口模式必须是 responses 或 chat_completions")
    return value


def ask_value(prompt, validate, *, default="", secret=False):
    while True:
        if secret:
            # getpass normally falls back to echoed stdin when no secure terminal
            # is available. Stop instead; never accept a key with echo enabled.
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    value = getpass.getpass(prompt)
            except getpass.GetPassWarning as error:
                raise ValueError("当前终端无法隐藏密钥输入。请在 Terminal / PowerShell 等交互终端重新运行；不会使用明文输入") from error
        else:
            value = input(prompt)
        try:
            return validate(value.strip() or default)
        except ValueError as error:
            # Validators must never include the submitted value.
            print(f"  {error}，请重新输入。", flush=True)


@dataclass(frozen=True)
class PortalConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    database: Path = Path("runtime/lumen_desk.db")
    provider: str = "local"
    api_key: str = field(default="", repr=False)
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_mode: str = "responses"

    def model_provider(self) -> ResponsesProvider | None:
        if self.provider == "local":
            return None
        provider_class = ChatCompletionsProvider if self.api_mode == "chat_completions" else ResponsesProvider
        return provider_class(api_key=self.api_key, model=self.model, api_base=self.base_url)


def argument_parser(*, launcher: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lumen 本地业务网站与可选真实回复模型（连接配置不写文件）")
    parser.add_argument("--host", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, help="监听端口，默认 8080")
    parser.add_argument("--database", type=Path, help="SQLite 文件，默认 runtime/lumen_desk.db")
    parser.add_argument("--provider", choices=["local", "openai"], help="local 离线运行；openai 缺少连接配置时在终端询问")
    parser.add_argument("--base-url", help="模型 API 前缀；未设置时在终端询问")
    parser.add_argument("--model", help="服务商提供的模型 ID，按原样发送；未设置时在终端询问")
    parser.add_argument("--api-mode", choices=["responses", "chat_completions"], help="接口协议；交互输入时可按编号选择")
    parser.add_argument("--check-model", action="store_true", help="输入配置并发送一次连接检查后退出，不启动网站")
    parser.add_argument("--no-input", action="store_true", help="禁止交互输入；缺少配置时直接报错，适合自动化")
    if launcher:
        parser.add_argument("--no-browser", action="store_true", help="启动网站，但不自动打开浏览器")
    return parser


def config_from_args(args: argparse.Namespace, *, root: Path | None = None,
                     environ: dict[str, str] | None = None, interactive: bool = False) -> PortalConfig:
    root = (root or Path.cwd()).resolve()
    # Copy only. Do not load .env, mutate os.environ, export to the parent shell,
    # cache per-directory settings, or persist connection details anywhere.
    values = dict(os.environ if environ is None else environ)

    def setting(arg: str, env: str, default: str) -> str:
        override = getattr(args, arg, None)
        return str(override).strip() if override is not None else values.get(env, default).strip()

    provider = setting("provider", "SUPPORT_AGENT_PROVIDER", "local")
    if provider not in {"local", "openai"}:
        raise ValueError("SUPPORT_AGENT_PROVIDER 必须是 local 或 openai")
    try:
        port = int(setting("port", "SUPPORT_WEB_PORT", "8080"))
    except ValueError as error:
        raise ValueError("SUPPORT_WEB_PORT 必须是端口整数") from error
    if not 1024 <= port <= 65535:
        raise ValueError("端口应介于 1024 与 65535 之间")
    database = Path(setting("database", "SUPPORT_DESK_DB", "runtime/lumen_desk.db")).expanduser()
    if not database.is_absolute():
        database = root / database
    host = setting("host", "SUPPORT_WEB_HOST", "127.0.0.1")
    if not host or any(c.isspace() for c in host):
        raise ValueError("SUPPORT_WEB_HOST 必须是有效的监听地址")
    if provider == "local":
        return PortalConfig(host=host, port=port, database=database)

    base_url = setting("base_url", "OPENAI_BASE_URL", "")
    key = values.get("OPENAI_API_KEY", "").strip()
    model = setting("model", "OPENAI_MODEL", "")
    api_mode = setting("api_mode", "OPENAI_API_MODE", "")

    # Validate supplied values before asking for more. Errors never echo them.
    if base_url:
        base_url = validate_base_url(base_url)
    if key:
        key = validate_key(key)
    if model:
        model = validate_model(model)
    if api_mode:
        api_mode = validate_api_mode(api_mode)

    missing = [name for name, value in [("OPENAI_BASE_URL", base_url), ("OPENAI_API_KEY", key), ("OPENAI_MODEL", model)] if not value]
    if missing:
        if not interactive or getattr(args, "no_input", False):
            raise ValueError("缺少模型连接配置：" + "、".join(missing)
                             + "。请在交互终端直接运行 python3 scripts/start_demo.py --provider openai 按提示输入；"
                               "自动化可通过当前进程环境变量提供，本地演示使用 --provider local。不会读取 .env 文件")
        print("\n真实回复模型 · 临时连接设置", flush=True)
        print("请填写服务商提供的信息；输入仅供本次运行使用，不写文件。Ctrl+C 可取消。", flush=True)
        if not base_url:
            base_url = ask_value("API 地址（Base URL，回车使用 https://api.openai.com/v1）：",
                                 validate_base_url, default="https://api.openai.com/v1")
        if not key:
            key = ask_value("API Key（输入隐藏，粘贴后按 Enter）：", validate_key, secret=True)
        if not model:
            model = ask_value("模型 ID（按服务商提供的名称原样输入）：", validate_model)
        if not api_mode:
            print("接口类型：1 = Chat Completions（/chat/completions）；2 = Responses（/responses）。", flush=True)
            api_mode = ask_value("选择接口 [1/2，回车默认 2]：",
                                 lambda v: validate_api_mode({"1": "chat_completions", "2": "responses"}.get(v, v)),
                                 default="responses")
        print("已接收临时配置，API Key 不会显示或保存。程序结束后，交互输入不保留。\n", flush=True)
    return PortalConfig(host, port, database, provider, key, model, base_url, api_mode or "responses")

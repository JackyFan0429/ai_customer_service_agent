# 早期独立 RAG 演示

[当前网站](../../README.zh-CN.md) · [English](README.md)

该入口使用 **19 条合成知识**展示检索和回答策略，不包含当前网站的账号、业务查询工具或工单工作台。当前网站通过 `scripts/start_demo.py` 启动。

## 本地运行

在项目根目录使用 Python 3.11+：

```bash
python3 -m support_agent.web --provider local --host 127.0.0.1 --port 8081
```

打开 [http://127.0.0.1:8081](http://127.0.0.1:8081)。此独立网页没有登录鉴权，仅用于本地演示；其 SQLite 对话与当前网站数据库分开保存。

单次命令行查询：

```bash
python3 -m support_agent.cli --provider local --json "ClientA Base URL"
```

预期路由为 `answer`，引用 `demo:setup`。知识和答复为中文，CLI 对话仅保留在当前进程，网页对话持久化保存。

## 评测与导入

```bash
python3 scripts/evaluate_agent.py --provider local --output runtime/legacy-evaluation.json --fail-on-regression evals/results/after.json
```

预期 **48/48 场景、63/63 轮**通过。这是合成开发回归，不是客户问题解决率。

[架构](architecture.zh-CN.md) · [知识整理](operations.zh-CN.md) · [评测](evaluation.zh-CN.md) · [回答策略](safety.zh-CN.md) · [数据范围](data_scope.zh-CN.md)

根目录 Docker Compose 启动的是**当前网站**，不是此旧入口。需要交互填写模型配置时，请使用[当前网站说明](../operations.zh-CN.md)；旧入口没有三阶段启动检测功能。


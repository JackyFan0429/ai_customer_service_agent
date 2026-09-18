# 本地运行与知识维护

[English](operations.md) | **简体中文**

请先完成[主教程](../README.zh-CN.md)。下面前三步只使用随包合成资料，可以直接复现。所有命令在项目根目录、已激活的 Python 环境中执行。

## 1. 复制一份演示语料

将随包资料复制到工作文件：

```bash
python -c "from pathlib import Path; import shutil; Path('runtime').mkdir(exist_ok=True); shutil.copyfile('support_agent/demo/corpus.jsonl', 'runtime/copied_demo.jsonl')"
```

预期生成 `runtime/copied_demo.jsonl`，包含相同的 19 条虚构记录。尝试修改知识时可以编辑这份副本，保留仓库原始语料不变，以便与基线比较。

## 2. 指定这份文件运行

```bash
python -m support_agent.web --provider local --host 127.0.0.1 --port 8081 --corpus runtime/copied_demo.jsonl --database runtime/custom_demo.db
```

打开 [http://127.0.0.1:8081](http://127.0.0.1:8081)，发送 `ClientA Base URL 怎么配置？`，预期得到虚构配置说明。复制后的记录仍带有 `synthetic: true`，所以状态栏依然显示演示资料。此命令使用单独的数据库，按 Ctrl+C 停止服务。

也可以使用 CLI：

```bash
python -m support_agent.cli --provider local --corpus runtime/copied_demo.jsonl --json "ClientA Base URL 怎么配置？"
```

Web 会话保存在 SQLite，CLI 历史只保存在进程内存。Web 是无认证的本地原型。如果使用 `pip install -e .` 安装，额外提供 `support-agent` 和 `support-agent-web` 两个命令入口。

## 3. 生成知识复核队列

```bash
python scripts/review_knowledge.py --corpus runtime/copied_demo.jsonl --as-of 2026-09-19 --output runtime/demo_knowledge_review
```

打开 `runtime/demo_knowledge_review/summary.json` 和 `review_queue.jsonl`。部分夹具专门模拟过期资料，队列会记录来源、内容哈希、到期原因，以及待填写的核验人、日期和依据。此命令不会续期事实，也不会修改输入语料；其他演示记录的远期日期只用于稳定复现，不能直接套用到真实政策。

## 4. 可选：准备自己的私有输入

本节是导入流程参考，**不能仅凭公开演示文件直接运行**，需要先提供自己的脱敏案例与来源文件。公开仓库不附带原始业务数据。

- 将案例统一整理到 `data/input/case_kb_preview/canonical_cases.jsonl`，消息包含 `message_id`、`role`、`content`；先把渠道特有的消息 ID 映射到 `message_id`。
- 配置 `scripts/enrich_cases.py` 和 `scripts/extract_pdf_official_kb.py` 的产品、客户端规则，当前标签只是虚构示例。
- 按[官方来源结构](official_kb_policy.md)准备 `knowledge/official/` 内的 JSONL，整个目录保持私有。
- 如需抽取 PDF，先执行 `python -m pip install -e ".[pdf]"`。

处理已规范化的案例：

```bash
python scripts/enrich_cases.py --input data/input/case_kb_preview/canonical_cases.jsonl --output data/output/enriched
```

如需抽取 PDF，将下面的示例文件名和日期换成自己的来源文件和实际提取日期：

```bash
python scripts/extract_pdf_official_kb.py --input knowledge/official/sources/support_knowledge_base.pdf --snapshot-date 2026-09-19 --output knowledge/official/internal/support_internal_pdf.jsonl --audit knowledge/official/audit/support_internal_pdf_audit.json --report knowledge/official/audit/support_internal_pdf_report.json
```

`snapshot-date` 是提取日期，不能证明政策仍有效。未提供 `--verified-at` 时，抽取记录的到期日期会有意早于快照日期，等待来源核验。仅在确实复核对应政策后填写核验日期；有效性混杂的文档应逐条复核，不能整体续期。重新抽取前请备份已有输出。

## 5. 构建并校验私有语料

准备好输入，并完成必要核验后：

```bash
python scripts/ingest_official_kb.py --input knowledge/official --output data/output/official_kb
python scripts/check_case_conflicts.py --cases data/output/enriched/case_summaries.jsonl --official-kb data/output/official_kb/official_kb.jsonl --output data/output/conflicts
python scripts/build_retrieval_corpus.py --official-kb data/output/official_kb/official_kb.jsonl --cases data/output/enriched/case_summaries.jsonl --conflicts data/output/conflicts/case_conflict_assessments.jsonl --output data/output/retrieval
python scripts/validate_official_pipeline.py --official-kb data/output/official_kb/official_kb.jsonl --cases data/output/enriched/case_summaries.jsonl --assessments data/output/conflicts/case_conflict_assessments.jsonl --corpus data/output/retrieval/retrieval_corpus.jsonl
```

当前流水线校验器要求 `review_after >= retrieved_at`，所以有意标记为过期的未核验 PDF 记录不能通过这一步。将其作为已验证快照使用前，应先解决来源核验问题，不能只为通过检查而修改日期。

校验通过后，明确指定自己的语料：

```bash
python -m support_agent.web --provider local --corpus data/output/retrieval/retrieval_corpus.jsonl
```

之后参考第 3 步，换成自己的语料路径和复核日期，定期执行 `scripts/review_knowledge.py`。未发现规则冲突不等于事实仍然正确。历史私有处理规模见[数据范围](data_scope.zh-CN.md)，不能当作公开演示数据量。

## 响应字段

| 字段 | 含义 |
| --- | --- |
| `answer` | 回答文本。 |
| `route` | `answer`、`clarify` 或 `escalate`。 |
| `reason` | 策略决策原因。 |
| `citations` | 实际提供给生成器的材料，或本地 provider 摘录的记录。 |
| `session_id` | 会话标识。 |
| `provider` | 所选 provider。 |

人工升级目前只产生提示与路由，创建真实工单需要渠道适配器。软件测试不能直接证明满意度、节省工时、真实解决率或模型费用。

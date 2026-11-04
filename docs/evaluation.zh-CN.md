# 评测

[首页](../README.zh-CN.md) · [English](evaluation.md)

软件检查、业务流程、检索和真实模型质量分别统计，均不等于线上解决率。

## v0.5.10 证据

| 层次 | 结果 | 限制 |
|---|---|---|
| 软件测试 | 292 项通过 | 模型 API 使用模拟响应 |
| 网站业务 | 29/29 场景 | 合成题的路由、工具及必要事实 |
| 旧版 RAG，v0.5.9 历史证据 | 48/48 场景、63/63 轮 | 本版未重跑 |
| 人工复核检索 | 30/30 标签通过，共 22 组 | 小型合成题集，题目已公开 |
| 真实模型 | 12 轮、34 次 API 调用 | 包含修复前问题及修复后复测，均为已知合成场景 |

[真实模型发现与边界](live-model-acceptance.zh-CN.md) · [本版证据](verification.zh-CN.md)。

## 检索过滤

保持 BM25 0.62＋字符 2/3-gram 0.38。以下在**同一份已复核 v3 知识和标签**上比较：旧 Top-4 覆盖度过滤，与新增的主题、能力范围、完整错误标识过滤。主题解析器去掉明确暂停的句段，不调用模型改写查询。

| 分区 | 有依据题 | 旧 Recall@4 | 新 Recall@4 | 新方案完整覆盖 | 知识缺失误召回：旧 → 新 |
|---|---:|---:|---:|---:|---|
| 开发集 | 17 | 76.47% | 100% | 17/17 | 2/2 → 0/2 |
| 历史保留集诊断 | 8 | 75% | 100% | 8/8 | 0/1 → 0/1 |

两侧另各有一道纯业务数据题，单独统计；新方案不为它们返回静态依据。[开发报告](../evals/releases/v0.5.10/retrieval-development.json) · [诊断报告](../evals/releases/v0.5.10/retrieval-historical.json)。

先生成开发报告冻结代码与数据哈希，再跑历史保留题。**两个分区此前都已在复核和分析中看过**，因此只能算回归诊断，不能称为独立盲测成绩。过滤规则面向 10 个内置业务 ID 和高覆盖度自定义 FAQ；新表达和新增知识仍需验证。

Recall@4 对每题必要知识命中的比例求平均；MRR 衡量第一个相关结果的名次，都不评价最终答案。知识缺失误召回只统计无答案题；当前余额和单次耗时属于动态查询，不进入这些分母。

[v0.5.6 方法对照](retrieval-comparison.zh-CN.md)及冻结语料保持原样。标签和知识不同，不把旧版本分数与新结果直接比较为质量提升。

## 复现

在项目根目录运行：

```bash
python3 -m pip install -e ".[pdf]"
python3 -m unittest discover -s tests -v
python3 scripts/evaluate_desk.py --as-of '2026-11-04T00:00:00+11:00' --output runtime/desk.json
python3 scripts/evaluate_agent.py --provider local --output runtime/rag.json --fail-on-regression evals/results/after.json
python3 scripts/validate_retrieval_dataset.py --dataset evals/retrieval/lumen-v3 --require-reviewed --output runtime/labels.json
python3 scripts/evaluate_reviewed_retrieval.py development --output runtime/retrieval-dev.json
python3 scripts/evaluate_reviewed_retrieval.py holdout --freeze runtime/retrieval-dev.json --output runtime/retrieval-diagnostic.json
```

检索每次使用新输出文件名；已有文件或冻结哈希不一致时拒绝运行。完整测试需要 PDF 可选依赖，网站和检索检查不需要。

## 后续衡量

用新增未见题和真实模型试运行，衡量首次有效回复时间、重复提问、无依据承诺、人工处理时长、建议采纳率及每个已解决工单成本。按相同工单类型比较，失败样本保留在分母中。

[管理员用量](admin-evidence.zh-CN.md)已汇总 Token、重试和费用估算。普通模型回复通常 3 次调用，内容修订可再加 2 次；依据摘要与回复同次生成。本地检索没有 Embedding API 费用，但尚不能证明总运营成本更低，也没有量化人力节省或收入提升。

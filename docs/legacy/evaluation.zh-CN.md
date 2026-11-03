# 早期 RAG 评测

[旧版入口](README.zh-CN.md) · [English](evaluation.md)

## 当前回归

```bash
python3 scripts/evaluate_agent.py --provider local --output runtime/evaluation.json --fail-on-regression evals/results/after.json
```

包含 19 条合成知识、48 个开发场景、63 轮消息，其中 14 个多轮场景；AI 辅助标签待本人复核。当前预期 **48/48 场景、63/63 轮**通过。

检查路由、必要及允许的知识 ID、必要答复要点和禁止结论。任一轮失败即场景失败，异常不移出分母。固定评测日期为 2026-09-19；证据 ID 匹配不等于逐句事实核验。

## 历史对照

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| 完整场景 | 39/48 | 48/48 |
| 完整轮次 | 53/63 | 63/63 |
| 正确路由 | 56/63 | 63/63 |
| 多轮场景 | 9/14 | 14/14 |
| 应升级召回 | 9/9 | 9/9 |

[修复前报告](../../evals/results/before.json) · [修复后报告](../../evals/results/after.json) · [历史补丁](../../evals/baselines/pre_iteration.patch)

当时修复了退款规则误升级、相似错误码混淆和追问丢主题。这些开发集结果不代表线上收益。

## 重建旧实现

补丁需要完全匹配的 **2026-09-19 修复后源码快照**，该快照未随包提供，当前源码已发生变化。若持有匹配源码，可运行：

```bash
python3 scripts/reproduce_baseline.py --source-root /path/to/matching-historical-source
```

脚本先校验已记录的源码哈希，再在临时目录应用补丁，检查旧实现哈希及结果。缺少或不匹配时立即停止。不能仅凭当前公开包重建当时实现；验证当前版本使用上方回归命令。

对照依赖输入、评分器及语料哈希，改变输入需新建基线。本地执行耗时不等于模型耗时；未测 Token / 成本记为 `null`，不记为零。完整测试见[当前评测说明](../evaluation.zh-CN.md)。


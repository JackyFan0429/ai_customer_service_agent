# 版本验证

[文档索引](README.zh-CN.md) · [English](verification.md)

## v0.5.7：文档与发布整理

2026-11-04 基于 v0.5.6 ZIP 独立构建。网站业务、模型接入、知识、检索实现及冻结实验结果沿用原版。

本次修改：
- 重写中英快速上手与说明，添加本地 SVG 语言按钮及可点击技术 / 测试徽章。
- 将当前网站、早期 RAG 和历史版本记录分开组织。
- 修正历史基线重建入口：明确要求匹配源码，并在打补丁前校验哈希。
- 扩大打包排除规则，过滤缓存、环境文件、数据库附属文件和编辑器备份；保留必要测试数据及审计证据。

| 检查 | 结果 | 证据 |
|---|---|---|
| 软件测试 | Python 3.12 下 **225 项通过** | [完整输出](../evals/releases/v0.5.7/tests.txt) |
| 网站业务 | **29/29 场景** | [报告](../evals/releases/v0.5.7/desk-workflow.json) |
| 旧版 RAG | **48/48 场景、63/63 轮**，无基线回归 | [报告](../evals/releases/v0.5.7/legacy-rag.json) |
| 数据集校验 | **30 题 / 22 组**，标签全部待本人复核 | [报告](../evals/releases/v0.5.7/dataset-validation.json) |

新增 7 项检查覆盖打包边界和历史源码校验。未重建旧实现本身，因为所需历史源码未随包提供。

本轮未发外部模型请求，也未构建 Docker。本地 API 测试使用模拟响应，没有重跑 v0.5.6 保留集或据此调参。

## 历史证据

| 版本 | 重点 | 记录 |
|---|---|---|
| v0.5.6 | 三种检索方法对照 | [分析](retrieval-comparison.zh-CN.md)、[冻结结果](../evals/retrieval/experiments/v0.5.6) |
| v0.5.5 | 独立检索集与分组划分 | [数据集](retrieval-dataset.zh-CN.md) |
| v0.5.4 | 业务与旧版 RAG 基线 | [基线说明](history/evaluation-baseline-v0.5.4.zh-CN.md) |
| v0.5.3 | 套餐、余额、配置主题切换 | [真实模型记录](topic-switch-live-v0.5.3.json) |
| v0.5.2 | 连续追问、退款和人工上下文 | [真实模型记录](multiturn-live-v0.5.2.json) |

[历史验证归档](history/verification-through-v0.5.6.zh-CN.md)保留早期截图和观察。历史真实模型成功不代表本版重新进行了 API 验证。

待做项仍为检索标签人工复核、覆盖度过滤改进、模型用量与成本汇总，详见[评测说明](evaluation.zh-CN.md)。


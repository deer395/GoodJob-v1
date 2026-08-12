# Phase 3A：渐进式混合岗位匹配

状态：部分验收；结构化传输已修复，但最终人工 Eval 未通过 LLM 进入无 JD 主排序的全部门槛。

## 2026-08-12 修订：baseline + 有限语义纠偏

第一次 36 条人工盲评显示让 LLM 与规则共同重建完整分数会显著退化。因此冻结为以下机制，直至独立盲评完成：

- baseline 仍是原 `evaluate()` 的 n-gram 与确定性规则结果；
- LLM 仅返回职业赛道关系：`same_track`、`close_track`、`transferable_but_not_target`、`unrelated`、`uncertain`；
- Python 调整固定为 `+6`、`+3`、`-3`、`-6`、`0`；低于 60 置信度时强调整收缩到 3 分；
- 明确、单一的算法/后端/前端/客户端/嵌入式/IC/芯片/硬件岗位，在用户目标不含对应职业方向时，不得获得正向调整；明确列出产品或数据的多岗位入口不触发该 guardrail；
- Provider 失败、超时或格式错误时调整恒为 0，最终分数与 baseline 完全相同；
- fingerprint 固定包含岗位基础字段、画像、prompt version 与 model；列表浏览不调用 LLM。

旧 36 条样本仅用于诊断。独立盲评集 `evaluation/phase3a_baseline_adjustment/human_review_blind.csv` 已填写并评测；正式结果见 `docs/evaluation/phase3a-baseline-adjustment-final-eval.md`。其排序信号改善，但当时 24 次调用中有 7 次失败。

2026-08-12 可靠性修复冻结：当前 Provider 是 DeepSeek V4 Flash。其 strict tool schema 在默认 thinking mode 下会返回 HTTP 400；改为官方要求的 non-thinking transport 后，12 条未参与人工评测的可靠性样本得到 12 / 12 有效结构化返回。结构化版本固定为 `screening-v3-strict-schema`：strict schema 仅传输 `role_family`、`relation_to_target_track`、`confidence`；Prompt 的职业赛道问题、baseline、调整幅度、guardrail、模型均不变。

最终 16 条独立盲评见 `docs/evaluation/phase3a-reliability-final-eval.md`。Provider 与 schema 已稳定，但 revised candidate 的 Spearman 为 0.561（baseline 0.369）、Top-10 priority 2/3 均为 70%，且 Top-10 false high 由 0 变为 1。它未满足“false high 不增加”的冻结门槛。正式结论：停止优化无 JD 初筛；baseline 保持主排序，LLM 不凭当前证据自动进入主排序，仅可保留为明确触发的单岗位分析能力。

## 决策

岗位池首先给每个已配置画像的岗位生成 0–100 的“初筛相关度”。它只表示多个岗位之间值得优先查看的相对程度，不是适配概率、投递成功概率或 JD 满足率。

- Python 处理城市、明确届别/学历冲突、截止日期，以及最终透明的 component score 聚合。
- LLM 只在用户明确触发且已同意时，返回受限 JSON：岗位方向、与用户目标的语义关系、最近目标与真实文本中的能力线索；不得返回分数、投递建议、岗位要求或用户经历。
- 浏览岗位列表不调用 LLM。结果由岗位基础字段、画像、prompt 版本和模型组成 fingerprint 缓存；岗位或画像变化时旧结果失效。
- LLM 不可用时，系统继续以确定性规则和旧 n-gram 作为 fallback。
- 有完整 JD 的岗位可在初筛后主动进入深度分析；深度分析的证据、能力映射与建议不得反向篡改初筛相关度或硬规则。

## 放弃的实验

上一版“Level 1 信息不足 / Level 2 深度匹配”已归档在 `experiment/phase3a-layered-matching`。实际岗位库多为 Excel 基础字段而缺少完整 JD；把无 JD 岗位集中表达为“信息不足”降低了数百岗位的排序区分度，因此不采用该产品表达。

## 非目标

本阶段不引入 embedding、向量数据库或 reranker；不让 LLM 自由生成最终百分比或投递建议；不在列表浏览时批量调用 AI。

## 验收门槛

必须在固定样本、权重、prompt 与模型后，由用户填写盲评 `human_priority`。只有新旧方案在同一批样本上的排序、Top-K 与严重误判指标达到约定标准，且深度 JD 无 evidence 错配、无用户经历幻觉、全量工程测试通过，才可创建正式完成提交。

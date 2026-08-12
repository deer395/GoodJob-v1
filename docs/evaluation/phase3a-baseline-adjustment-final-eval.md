# Phase 3A baseline + limited semantic adjustment: independent evaluation

状态：机制冻结后的独立人工评测已完成；排序信号改善，但 Provider 稳定性未达到完成标准。因此 Phase 3A **尚未完成**，不创建完成提交，也不继续调权重或 Prompt。

## 方法与边界

- 盲评文件：`evaluation/phase3a_baseline_adjustment/human_review_blind.csv`，24 条真实岗位，与原 36 条 development / diagnostic set 无重叠。
- 人工标签由用户独立填写，未被模型生成、修改或回写：priority 3 有 2 条、2 有 3 条、1 有 9 条、0 有 10 条。
- Baseline 为 `f782c59` 已有的本地 n-gram 与确定性规则 `evaluate()`；候选只在其上使用冻结的职业赛道信号，Python 最多修正 6 分。Provider 失败时修正严格为 0，保留原始 baseline。
- 评测逐条只读正式 SQLite；不写回岗位、画像、缓存或人工标签。语义请求仅发送岗位基础字段和用户已授权的画像字段。
- Top-K 在同分时保留盲评文件的稳定原始顺序；Spearman 使用并列分数的平均名次。

## 人工标签分布

| priority | 数量 |
| --- | ---: |
| 3（高优先） | 2 |
| 2（值得关注） | 3 |
| 1（一般） | 9 |
| 0（低相关） | 10 |

## 正式比较

| 指标 | 本地 baseline | 冻结后的 revised candidate |
| --- | ---: | ---: |
| Spearman（与人工 priority） | 0.086 | 0.382 |
| Top-10 中 priority 2/3 | 4 / 10（40%） | 5 / 10（50%） |
| Top-20 中 priority 2/3 | 5 / 20（25%） | 5 / 20（25%） |
| Top-10 false high（priority 0） | 6 | 4 |
| Bottom-10 false low（priority 3） | 0 | 0 |

排序一致性、Top-10 实用性和严重高估均较 baseline 改善；Top-20 没有改善，但也没有退化。

## 语义纠偏审计

有效语义结果 17 / 24（70.8%）；失败 7 / 24（29.2%）：

| 失败类别 | 数量 | 候选分数行为 |
| --- | ---: | --- |
| `malformed_response` | 6 | adjustment = 0，保留 baseline |
| `timeout` | 1 | adjustment = 0，保留 baseline |

没有 rate limit、provider HTTP error、连接错误或 JSON transport parse failure。此前 36 条实验把所有失败合称 `AIUnavailable`，无法倒推出其真实类别；本次是首次具备该诊断粒度的记录。

本次能看出正确纠偏的例子包括：

- R004（飞猪，含产品类）：30 → 36，人工 priority 2；
- R005（千问办公，含产运设类）：30 → 33，人工 priority 3；
- R006（阿里健康，含数据分析师 / AI 产品经理）：55 → 61，人工 priority 3；
- R007（柠檬微趣，含策划 / 数据类）：30 → 33，人工 priority 2；
- R022（哔哩哔哩，含产品 / 产品运营）：30 → 36，人工 priority 2；
- R009 / R011 / R012 / R013 等技术或芯片方向入口：30 → 27，人工 priority 0。

也存在没有带来可验证增益的纠偏：R001、R019 从 0 升至 3，但人工均为 priority 1；R014、R016、R020 从 30 降至 27，但人工均为 priority 1。这些幅度受限，未改变其低优先语义，但表明稀疏多岗位信息仍不能被视为可靠的自动排序依据。

## 结论与停止点

本次独立盲评已经证明：在可获得结构化信号时，有限纠偏比原 baseline 更符合人工排序，且没有让 Top-K 或严重误判退化。它也证明了 fallback 安全：7 次失败均未改变 baseline。

但 Provider 有近三成失败，未满足既定的“正常情况下语义分析稳定返回”以及正式完成标准中的“Provider 稳定”。按已冻结的停止规则，**不再针对这份独立结果调整职业关系定义、Prompt、模型、权重或 guardrail，也不引入 embedding / reranker。**

当前应保留 baseline 作为无 JD 主排序；有限语义纠偏只能作为受控、可回退的增强。Phase 3A 不能据此宣告完成；后续若要继续，必须先以独立的 Provider 可靠性工作（而非调分或改人工标签）解决格式/超时问题，并重新定义是否需要新的独立验收，不能复用本集作为再次调参依据。

# Phase 3A hybrid matching evaluation

状态：第一次 candidate 为 `major_revision`；该 36 条样本现降级为 development / diagnostic set，不可用于最终验收。

## 样本与人工标签

同一批 36 条真实岗位被分层抽取到 `evaluation/phase3a_hybrid/human_review_blind.csv`。用户独立填写了全部 `human_priority`：3 分 4 条、2 分 8 条、1 分 11 条、0 分 13 条。标签未由模型生成或改写。

样本均为无完整 JD 的岗位基础信息，符合实际岗位池的主要数据分布。本轮画像为：2027 届、硕士、资源与环境专业；目标城市杭州/深圳/北京/上海/南京；目标方向产品经理/数据分析师；技能 Python/SQL。

## 固定的首次候选评估

首次候选运行对 36 条相同样本逐条调用结构化语义初筛，再由 Python 聚合。耗时 412.01 秒；19 条得到语义结果，17 条 `AIUnavailable` 后正确回退到本地规则和 n-gram。无法取得 provider 的真实 token/cost，故不估算成本。

| 指标 | f782c59 n-gram baseline | 首次 hybrid candidate |
| --- | ---: | ---: |
| Spearman（与人工 priority） | 0.502 | 0.166 |
| Top-10 中 priority 2/3 占比 | 70% | 60% |
| Top-20 中 priority 2/3 占比 | 40% | 30% |
| Top-10 false high（priority 0） | 2 | 4 |
| Bottom-10 false low（priority 3） | 0 | 0 |

候选没有证明优于 baseline，反而明显退化，因此不得以代码完成为由通过验收。

## 发现与有限修正

正向语义例子：产品经理（商业化）与策略产品经理能被识别为产品方向高度相关；数据分析师能识别到 SQL、Python、指标体系。

退化例子：部分纯算法/研发岗位被判为与数据分析“相关或相邻”，例如 NLP 算法工程师、软件开发工程师；另外 17 次 provider 失败使候选大量退化为保守 fallback，破坏排序稳定性。

评估后仅进行了一个产品级安全修正：当岗位方向完全是算法/研发且用户目标不包含算法/开发/工程时，`highly_related` 降为 `related`、`related` 降为 `adjacent`。该改动有聚焦单测，但**尚未重新进行预先固定的独立人工 Eval**；不得将它包装成通过结果。

## 深度 JD 验收与幻觉

本次盲评样本均无完整 JD，尚未执行 5–10 条深度 JD 验收。旧自由 `ai_score` 深度分析也尚未替换为结构化 requirement/evidence/capability mapping，因此不能声称 evidence 错配和用户经历幻觉均为零。

## 结论

第一次 candidate 为 `major_revision`，Phase 3A 不允许完成、不允许创建 `feat: complete phase 3a hybrid job matching` 提交。

## 后续有限修正（不使用本集作为通过依据）

已改为 baseline + bounded semantic adjustment：保留旧 baseline，LLM 只给职业赛道关系；Python 的调整上限为 6 分，Provider 失败时调整为 0。development set 的关键诊断结果为：

- 商业化产品经理：55 → 58；策略产品经理：55 → 58；
- 数据分析师：80 → 86；
- NLP 算法：0 → 0（语义关系为 `transferable_but_not_target`）；
- Java 后端：30 → 27；软件开发：30 → 27；
- 包含产品/数据的多岗位入口：30 → 33，未触发纯技术岗 guardrail。

这些结果只证明已知问题得到定向检查，**不构成通过证据**。机制已经冻结，等待 `evaluation/phase3a_baseline_adjustment/human_review_blind.csv` 的独立人工标签后再做正式比较。

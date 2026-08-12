# Phase 3A：baseline 主排序 + 主动 AI 深度分析

状态：已确认，等待正式收口提交。

## 问题

岗位池的大多数记录只有公司、岗位、城市等稀疏信息。产品需要先给用户稳定的查看优先级，再在用户对具体岗位感兴趣时提供更深入的判断；不能把不稳定的 AI 输出伪装成主匹配概率。

## 尝试与证据

1. **Layered matching：** 将无 JD 岗位表达为信息不足、完整 JD 才深度分析。真实岗位池大多数无 JD，导致大量结果同质化，降低筛选价值；已归档为实验。
2. **LLM 与规则共同重新评分：** 首轮 36 条独立 Eval 明显低于 baseline，停止。
3. **baseline + 有限语义纠偏：** baseline 保持主体，LLM 只给职业赛道关系并由 Python 限幅。独立 Eval 显示整体排序相关性改善；Provider 结构化输出随后修复为稳定返回。但最终 16 条独立 Eval 的 Top-10 false high 从 0 增至 1，未满足全部预先冻结门槛。

详细历史证据保留在 `docs/evaluation/`、`evaluation/` 和 `docs/decisions/phase-3a-hybrid-job-matching.md`，不重写为通过结论。

## 最终选择

- 无完整 JD 的岗位池使用本地确定性规则 + n-gram baseline 生成主 `match_score` 和排序。
- `match_score` 是相对查看优先级，不是适配概率、投递成功概率或 JD 满足率。
- LLM 不读取、刷新或影响岗位池主 `match_score`；“更新语义初筛”入口已废弃。
- structured LLM 的可靠调用能力保留给后续用户明确同意并主动触发的单岗位/完整 JD 分析，且不得虚构用户经历。当前页面仍是既有 `ai_score + reasons + risks` 单岗位辅助分析，完整 JD 的结构化能力/证据映射尚未完成，不在本轮临时扩展。

## 明确拒绝与停止条件

- 不继续调 Prompt、语义纠偏权重、职业赛道 guardrail 或无 JD 排序算法。
- 不引入 embedding、向量数据库或 reranker。
- AI 能否进入任何主决策链路必须由冻结机制下的独立人工 Eval 证明；工程上可调用不是产品准入依据。
- Phase 3B 邮件解析不在本决策卡范围内。

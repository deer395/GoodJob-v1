# CURRENT_STATUS

## 本轮最新状态（2026-08-12，优先于以下历史交接描述）

- Phase 2 第四批第一阶段（邮件自动关联状态安全、岗位删除数据完整性、全量导出与恢复、Alembic 迁移与备份基线）已正式验收。
- Phase 2 第四批第二阶段（核心可用性 P1 整改）已验收：雷达快捷筛选、岗位长标题与操作区布局、邮件同步诊断均已完成。
- 完整自动化回归已执行：`D:\ANACONDA\python.exe -m pytest manual_capture/tests -q --basetemp=D:\CODEX\LLMcampus\pytest_phase2_fourth_batch_recheck`，结果为 `60 passed, 1 warning`（Starlette `TestClient` 弃用警告）。
- 当前工作区仍有用户已有的未提交改动；本轮未创建 Git 提交。
- Phase 3A 的无 JD 岗位匹配实验、Provider 可靠性修复、独立人工 Eval 与人工页面验收均已完成；正式产品结论已确认，尚未创建收口 commit。

## 1. 当前阶段

- 当前交付状态：Phase 2 已完成至第四批第二阶段；Phase 3A 已完成产品与工程收口前的验收，等待最终 diff/regression 确认和正式提交。
- Phase 3B 邮件解析机制优化已实现，待真实邮箱与模型人工验收：本地候选召回可利用正文信号；LLM 仅接收编号脱敏证据句并返回多个带依据的候选事项；用户逐项确认后才更新申请。改期取消、提醒与补充材料保持人工处理，不自动改写既有进度。
- 新增能力必须先更新并获得对应决策卡确认，且不得突破本地、人工确认和用户最终投递权边界。

## 2. 当前有效状态

- GoodJobAI 已具备手动收录、秋招雷达、投递工作台、申请进度、表格/日历/邮件待确认视图，以及本地 CSV/XLSX 导入和用户触发的 ICS 导出。
- 雷达页提供临期、今日新增、本周截止、收藏、高匹配、待评估六个互斥快捷筛选；搜索词与筛选条件按 AND 组合，页面显示当前条件、结果数和一键清除入口。未配置画像时，高匹配入口不可用。
- 岗位卡的公司名与岗位名在桌面和窄屏均最多两行截断；“查看详情”等主操作保持独立可点击，完整标题仍在详情内可见。
- 邮件同步为用户主动触发的本地只读单次操作，固定扫描 INBOX 近 7 天、最多 50 封。页面显示进行中状态、候选/新增/去重计数；结构化计数不可用时明确显示“不可用”，不以 0 替代。
- 邮件同步失败使用不含敏感信息的诊断类别，并提供重试和 `/email-sync-help` 配置说明入口；Agent 启动异常会安全降级，不返回未处理的 500 错误。
- 邮件关联状态机、自动关联收紧规则和邮件解析策略未因第二阶段而改变；AI 匹配与邮件解析升级仍为后续方案。
- 岗位池的“初筛相关度”由本地城市、届别、学历、方向、技能等确定性规则与 n-gram baseline 生成；无 JD 岗位按此主排序。`match_score` 不受 LLM semantic cache 或语义纠偏影响，也不表示投递成功概率。
- Layered matching 已归档为实验；“LLM 与规则共同重建评分”在 Eval 中退化后停止；baseline + 有限语义纠偏虽改善整体相关性，但最终 Eval 的 false high 门槛未通过，故不进入主排序。
- DeepSeek V4 Flash structured output 已完成可靠性修复，供后续经验证的主动单岗位/完整 JD 深度分析复用。当前页面保留的 AI 单岗位辅助分析仍输出既有 `ai_score + reasons + risks`，尚未实现完整 JD 的结构化证据映射。废弃的“更新语义初筛”入口已删除，不再暗示 AI 会刷新岗位池主排序。
- 最新完整回归使用临时 SQLite：`80 passed, 1 warning`；warning 为既有 Starlette `TestClient` 弃用提示，与本轮无关。较前一轮少 1 条，是删除废弃“更新语义初筛”交互及其专用缓存测试后的同步结果。

## 3. 当前待处理事项

- Phase 3B 已在用户授权后实现；待真实 IMAP、真实模型和人工页面验收后，再决定是否收口。
- 如需进行本机运行验收，应由拥有 `manual_capture/campusai_manual.db` 文件权限的本地终端启动应用，并按既有恢复/迁移说明完成启动检查；本文件不将该运行环境操作记为已完成事实。

## 4. 当前材料与信息来源

- 长期项目背景与边界：[PROJECT_MASTER.md](PROJECT_MASTER.md)。
- 全局工程与产品规则：[AGENTS.md](AGENTS.md)。
- 产品决策记录：[docs/decision-log.md](docs/decision-log.md)。
- Phase 3A 正式决策卡：[docs/decisions/phase-3a-baseline-primary-ranking.md](docs/decisions/phase-3a-baseline-primary-ranking.md)。历史实验卡与 Eval 报告保留在 `docs/decisions/`、`docs/evaluation/` 与 `evaluation/`。
- 主应用与测试：[manual_capture/app.py](manual_capture/app.py)、[manual_capture/tests](manual_capture/tests)。

## 5. 下一次新对话的启动指令

```text
在 D:\CODEX\LLMcampus 接手 GoodJobAI。先完整阅读 AGENTS.md、PROJECT_MASTER.md、CURRENT_STATUS.md、docs/decision-log.md 和 docs/decisions/phase-3a-baseline-primary-ranking.md，并执行 git status。无 JD 岗位池必须保持本地 baseline 主排序，LLM 不得影响主 match_score；“更新语义初筛”已废弃。Phase 3B 邮件解析尚未开始，未经用户明确授权不得进入。保留本地、人工确认和最终投递权边界；不要擅自提交 Git。
```

## 6. 更新依据

- 更新时间：2026-08-12。
- 本状态基于 Phase 3A 独立人工 Eval、Provider 可靠性测试、人工页面验收和实际执行的完整自动化回归结果生成。
- 本文件不记录易变的服务端口、进程状态或未确认的运行环境结论。

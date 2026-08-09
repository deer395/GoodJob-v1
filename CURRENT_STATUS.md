# CURRENT_STATUS

## 本轮最新状态（2026-08-10，优先于以下历史交接描述）

- Phase 2 第四批第一阶段（邮件自动关联状态安全、岗位删除数据完整性、全量导出与恢复、Alembic 迁移与备份基线）已正式验收。
- Phase 2 第四批第二阶段（核心可用性 P1 整改）已验收：雷达快捷筛选、岗位长标题与操作区布局、邮件同步诊断均已完成。
- 完整自动化回归已执行：`D:\ANACONDA\python.exe -m pytest manual_capture/tests -q --basetemp=D:\CODEX\LLMcampus\pytest_phase2_fourth_batch_recheck`，结果为 `60 passed, 1 warning`（Starlette `TestClient` 弃用警告）。
- 当前工作区仍有用户已有的未提交改动；本轮未创建 Git 提交。

## 1. 当前阶段

- 当前交付状态：Phase 2 已完成至第四批第二阶段，等待用户确定下一轮范围。
- 已验收范围不包括第四批第三阶段；AI 匹配策略升级和邮件解析策略升级均尚未开始。
- 新增能力必须先更新并获得对应决策卡确认，且不得突破本地、人工确认和用户最终投递权边界。

## 2. 当前有效状态

- GoodJobAI 已具备手动收录、秋招雷达、投递工作台、申请进度、表格/日历/邮件待确认视图，以及本地 CSV/XLSX 导入和用户触发的 ICS 导出。
- 雷达页提供临期、今日新增、本周截止、收藏、高匹配、待评估六个互斥快捷筛选；搜索词与筛选条件按 AND 组合，页面显示当前条件、结果数和一键清除入口。未配置画像时，高匹配入口不可用。
- 岗位卡的公司名与岗位名在桌面和窄屏均最多两行截断；“查看详情”等主操作保持独立可点击，完整标题仍在详情内可见。
- 邮件同步为用户主动触发的本地只读单次操作，固定扫描 INBOX 近 7 天、最多 50 封。页面显示进行中状态、候选/新增/去重计数；结构化计数不可用时明确显示“不可用”，不以 0 替代。
- 邮件同步失败使用不含敏感信息的诊断类别，并提供重试和 `/email-sync-help` 配置说明入口；Agent 启动异常会安全降级，不返回未处理的 500 错误。
- 邮件关联状态机、自动关联收紧规则和邮件解析策略未因第二阶段而改变；AI 匹配与邮件解析升级仍为后续方案。

## 3. 当前待处理事项

- 等待用户确认下一轮产品目标与范围；在新范围确认前，不进入第四批第三阶段。
- 如需进行本机运行验收，应由拥有 `manual_capture/campusai_manual.db` 文件权限的本地终端启动应用，并按既有恢复/迁移说明完成启动检查；本文件不将该运行环境操作记为已完成事实。

## 4. 当前材料与信息来源

- 长期项目背景与边界：[PROJECT_MASTER.md](PROJECT_MASTER.md)。
- 全局工程与产品规则：[AGENTS.md](AGENTS.md)。
- 产品决策记录：[docs/decision-log.md](docs/decision-log.md)。
- 第四批决策卡：[docs/decisions/phase-2-fourth-batch-data-safety-usability.md](docs/decisions/phase-2-fourth-batch-data-safety-usability.md)。
- 主应用与测试：[manual_capture/app.py](manual_capture/app.py)、[manual_capture/tests](manual_capture/tests)。

## 5. 下一次新对话的启动指令

```text
在 D:\CODEX\LLMcampus 接手 GoodJobAI。先完整阅读 AGENTS.md、PROJECT_MASTER.md、CURRENT_STATUS.md、docs/decision-log.md 和当前决策卡，并执行 git status。当前已验收至 Phase 2 第四批第二阶段；不得进入第三阶段的 AI 匹配或邮件解析策略升级，除非用户先确认新的决策卡。保留本地、人工确认和最终投递权边界；不要擅自提交 Git。
```

## 6. 更新依据

- 更新时间：2026-08-10。
- 本状态基于本轮已确认的第四批第一、二阶段验收结论及实际执行的完整自动化回归结果生成。
- 本文件不记录易变的服务端口、进程状态或未确认的运行环境结论。

# CURRENT_STATUS

## 1. 当前阶段

- 当前正在进行的工作：Phase 1 四个闭环完成后的交接与文档整理；尚未启动下一阶段功能开发。
- 当前阶段目标：形成可由新对话直接接手的项目主文档与即时状态文档，并保留已确认可用的本地演示数据集。
- 当前阶段起点：闭环 4 的申请进度、时间线、漏斗和本地日历视图已实现并验证。
- 当前阶段结束条件：交接文档经用户确认，且用户明确授权下一阶段的具体范围后才开始新增功能。

## 2. 当前有效状态

- GoodJobAI 的闭环 1—4 已实现：手动收录岗位、秋招雷达、投递工作台、申请进度与本地日历视图。
- 闭环 4 包含 Application 状态流转、ApplicationEvent 时间线、下一步行动及计划时间、漏斗和列表/日历视图。
- 列表与日历视图使用统一的 Tab 模板片段，已解决两页 Tab 样式不一致和静态 CSS 缓存导致的默认 HTML 样式问题。
- 本地数据库当前已清空原岗位及关联申请记录，并写入 20 条中文模拟校招岗位；求职画像被保留。用户已确认该模拟数据结果没有问题，数据应继续保留。
- 原数据库在清空前已备份为 `manual_capture/backups/before-demo-seed-20260806-150359.db`。
- 数据库迁移版本已明确验证到 `20260806_progress (head)`。
- 已运行的自动化测试最近一次结果为 `20 passed`；该结果覆盖闭环 1—4 和日历数据投影测试。
- 用户要求暂不创建新的 Git 提交；当前工作区存在未提交变更，后续不得擅自提交。

## 3. 当前正在处理的问题

### 交接文档完成度

- 问题：新对话需要同时掌握长期规则和即时状态。
- 已知事实：`PROJECT_MASTER.md` 已创建并按修复清单调整；本文件用于补充当前即时状态。
- 未解决内容：等待用户确认交接文档是否足以开始下一阶段。
- 阻断条件：在下一阶段范围未获明确授权前，不开始新功能实现。

### 下一阶段范围

- 问题：下一阶段尚未收到具体的功能说明或授权文本。
- 已知事实：Excel/CSV 导入明确不属于 Phase 1，统一留待 Phase 2；20 条模拟数据应保留。
- 未解决内容：除导入范围外，下一阶段的功能目标和边界待用户提供。
- 阻断条件：未获具体授权前，不开始新功能实现。

## 4. 当前材料与信息来源

- 长期项目背景与边界：[PROJECT_MASTER.md](PROJECT_MASTER.md)。
- 全局工程与产品规则：[AGENTS.md](AGENTS.md)。
- 即时状态文档：本文件 `CURRENT_STATUS.md`。
- 产品决策记录：[docs/decision-log.md](docs/decision-log.md)。
- 闭环 4 决策卡：[docs/decisions/loop-4-application-progress.md](docs/decisions/loop-4-application-progress.md)。
- 主应用与数据访问：[manual_capture/app.py](manual_capture/app.py)。
- 申请进度列表模板：[manual_capture/templates/progress.html](manual_capture/templates/progress.html)。
- 申请进度日历模板：[manual_capture/templates/calendar.html](manual_capture/templates/calendar.html)。
- 列表/日历共享 Tab 模板：[manual_capture/templates/_progress_view_tabs.html](manual_capture/templates/_progress_view_tabs.html)。
- 样式文件：[manual_capture/static/app.css](manual_capture/static/app.css)。
- 自动化测试：[manual_capture/tests/test_manual_capture.py](manual_capture/tests/test_manual_capture.py)。
- 当前 SQLite 数据库：`manual_capture/campusai_manual.db`。
- 最近闭环 4 Alembic 迁移：[alembic/versions/20260806_application_progress.py](alembic/versions/20260806_application_progress.py)。
- 原始数据备份：`manual_capture/backups/before-demo-seed-20260806-150359.db`。

## 5. 当前采用的方案

- 申请进度使用 Application 与 ApplicationEvent 建模，岗位与申请流程状态分离。
- 申请进度默认列表视图展示漏斗、阶段筛选、卡片和时间线；日历视图只投影既有事件、岗位 DDL 与 `next_action_due_at`。
- 日历颜色约定：DDL 为绿色、面试为蓝色、测评/笔试为黄色、已投递为灰色、下一步计划为红色。
- 列表与日历视图的切换器必须继续使用共享模板 `_progress_view_tabs.html`，并使用相同 CSS 版本参数，避免再次分支漂移或缓存不一致。
- 不得修改的部分：已确认的 Application 状态、事件补建规则、漏斗“曾到达阶段”口径、最终投递权归用户。
- 暂定部分：下一阶段的具体范围和是否启动 Phase 2，待用户决定；模拟数据已确认保留。

## 6. 最近完成的关键工作

- 实现并验证申请进度的时间线、推进阶段、添加事件、撤回、结束、漏斗和本地日历视图。
- 修复时间线展示为最近 3 条优先、完整时间线可展开、事件数量可见、时间格式友好。
- 修复列表/日历 Tab 的 CSS 缓存和样式不一致问题，实际截图验证两视图均显示按钮样式。
- 创建 `PROJECT_MASTER.md`，并按 `docs/Codex指令_修复PROJECT_MASTER.md` 完成 1→7 项修正。
- 备份原本地数据库后，写入 20 条中文模拟岗位用于人工验收。

## 7. 待完成事项

### 阻断项

- 用户明确授权下一阶段的具体功能范围。验收条件：用户给出清晰、可执行的阶段目标与边界。

### 必须完成项

- 确认交接文档。验收条件：用户确认 `PROJECT_MASTER.md` 与 `CURRENT_STATUS.md` 可作为新对话接手材料，或给出需修正项。

### 可延后项

- 是否将当前未提交改动创建 Git 提交。验收条件：仅在用户明确要求提交后执行。

## 8. 当前未决问题

### 缺少材料

- 下一阶段的功能说明或授权文本：待用户提供。

### 缺少验证

- 无已确认的当前缺少验证项。

### 存在方案冲突

- 无。Excel/CSV 导入已明确归入 Phase 2。

### 需要用户决策

- 下一阶段是否启动，以及启动的功能边界。
- 何时创建 Git 提交。

### 需要外部信息核实

- 无。

## 9. 当前风险与限制

- 当前 SQLite 数据已被演示数据替换；恢复真实数据需要显式使用已创建的备份，不能默认覆盖模拟数据。
- 工作区包含未提交变更；用户已明确要求暂不提交，后续操作应避免混入无关改动。
- 本地服务地址和运行进程属于易变运行态；新对话开始时必须重新检查，不能假设仍在运行。

## 10. 下一次新对话的启动指令

```text
在 D:\CODEX\LLMcampus 接手 GoodJobAI。先完整阅读 AGENTS.md、PROJECT_MASTER.md、CURRENT_STATUS.md，并执行 git status。当前处于 Phase 1 完成后的交接阶段，未获得下一阶段具体授权前不得新增功能或提交 Git。保留现有 20 条模拟岗位和数据库备份，不要覆盖数据。先询问或读取用户提供的下一阶段范围；若用户要求继续实现，先核对相关决策卡、代码、迁移和测试，再按确认范围执行。
```

## 11. 最后更新时间与更新依据

- 更新时间：2026-08-06。
- 本状态基于本长对话截至当前的最新用户确认、已执行的实现与验证结果生成。
- 未能确认的下一阶段范围已明确标为待确认；模拟数据保留与导入归属已确认。

## 下次更新时应删除或替换的易过期信息

- 当前阶段为“交接与文档整理”的描述。
- 当前模拟数据数量、数据库备份路径。
- 最近测试结果、数据库迁移版本和本地服务运行状态。
- 未提交变更与“暂不提交 Git”的用户指令。
- 下一阶段授权及所有待确认项。

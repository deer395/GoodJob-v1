# Phase 2 第三批 A：本地 IMAP Agent 与安全邮件关联

状态：已确认，实施中（2026-08-07）

- 用户目标：用户手动执行一次本地 IMAP 同步后，安全识别求职邮件、自动关联高置信事件，并将其余结果交由用户确认。
- 数据边界：授权码和 Agent Token 仅从 `.env` 读取；不保存完整正文、附件、邮箱地址或凭据。持久化数据仅包含脱敏摘要、有限证据和结构化提案。
- 主操作：仅支持 `python manual_capture/imap_agent.py --once` 与 `--once --dry-run`；没有守护进程、自动启动或多邮箱。
- 状态：`pending`、`auto_applied`、`confirmed`、`dismissed`、`parse_failed`。
- 自动化：仅在邮件解析启用、分类/公司/岗位均强匹配、唯一候选且置信度不低于 90 时创建 ApplicationEvent；候选时间绝不自动写入日历时间。
- 非目标：OCR、定时同步、自动回复、推送、全文邮件搜索、简历分析和自动投递。
- 验收：只读 IMAP、dry-run 无副作用、去重事务一致、AI/Token 失败安全降级、队列可确认/改关联/驳回。

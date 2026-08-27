# GoodJobAI V1
GoodJobAI 是一个面向中国校招生的本地优先求职管理助手，帮助用户收录岗位、追踪投递进度与下一步行动。
> V1 原则：系统负责整理与提醒；投递、阶段变更和关键时间始终由用户最终确认。
## 功能
- 岗位收录、岗位池、求职雷达与本地规则匹配解释。
- 投递工作台、申请时间线、测评/笔试、面试、Offer 与结束状态追踪。
- 用户主动触发的本地只读 IMAP 邮件同步，生成带脱敏证据的待确认 proposal。
- 本地 SQLite 数据导出与隔离恢复。
## 技术栈
Python、FastAPI、Jinja2、HTMX、SQLite、SQLAlchemy、Alembic，以及可选的 OpenAI-compatible AI 服务。
## 快速开始
需要 Python 3.11+：
```powershell
python -m pip install -r manual_capture/requirements.txt
python -m uvicorn manual_capture.app:app --app-dir . --reload
```
启动后访问 <http://127.0.0.1:8000>。首次启动会创建本地 SQLite 数据库并自动执行 Alembic migration。
## 隐私与邮件安全
- 默认岗位和申请管理无需外部服务；AI 与 IMAP 均为用户主动启用的可选能力。
- 不要提交 `.env`、邮箱授权码、API Key、完整邮件正文或本地数据库。
- 完整邮件正文不会写入应用数据库；仅保存标题、发件域名、脱敏摘要和人工核对所需的证据片段。
- 无可靠时间锚点的相对时间（如“收到邮件后 48 小时”“明晚”）不会被猜测为绝对 Deadline。
- 邮件 proposal 必须由用户确认后，才会写入正式申请事件；改期、取消、补充材料和模糊关联不会静默改写申请进度。
## 测试
```powershell
$env:CAMPUSAI_DB_PATH = "$PWD\pytest_local\campusai.db"
python -m pytest manual_capture/tests -q --basetemp "$PWD\pytest_local\tmp"
```
V1 freeze 验收：112 passed；重建 realistic 20-case 邮件 benchmark 为 19/19 candidate recall、27/27 required-event coverage、0 Critical Error、0 incorrect Deadline、0 silent auto-confirm。
## 不包含的能力
- 自动登录招聘平台、填写表单或提交申请。
- 批量投递或爬取受限招聘平台。
- 上传完整邮件、简历、截图、授权码或 API Key。
## 使用说明
本仓库提供的是本地运行的源代码，不是已部署的公共网站。每位使用者 clone 后在自己的电脑启动应用，访问自己的 `http://127.0.0.1:8000`，并拥有独立的本地数据库。

# GoodJobAI

> 面向中国校招生的「本地优先」求职管理助手 —— 把散落在官网、BOSS 直聘、牛客、公众号里的岗位，收进一个可追踪、可解释、不依赖云端的工作台。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-后端-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLite-本地存储-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Local--first-本地优先-2ea44f?style=for-the-badge" alt="Local-first">
</p>

---

## 它解决什么问题

秋招是一场「信息 + 时间」的双线作战：岗位分散在十几个渠道，投递有截止日期，投完之后还有测评、笔试、面试、Offer 一路要跟进。最怕的不是没岗位，而是**忘了投、投混了、不知道下一步该干什么**。

GoodJobAI 的目标很明确：**帮你在截止日期前，完成真正适合自己的有效投递，并始终清楚每一份申请的下一步行动。**

它不是自动海投工具，也不是邮件待办清单。它是一条完整的求职流水线：

```
发现岗位 → 收录 → 判断值不值得投 → 排优先级 → 准备材料 → 手动投递 → 持续追踪
```

> **核心理念：系统负责整理与提醒，最终投递权永远在你自己手里。**
> 投递、阶段变更和关键时间，始终由你亲自确认。

---

## 核心特性

### 📥 岗位收录 —— 30 秒收下一条岗位

在官网、BOSS、牛客或公众号看到一个岗位，回到 GoodJobAI 一键收录。只需填写**公司、岗位、城市**三个必填项，投递链接、薪资、部门、截止日期、来源等都可以随手补充。

- 截止日期临近 3 天自动标记「临近截止」，过期标「已逾期」
- 重复岗位自动拦截提醒，由你决定是更新原记录还是确认新增
- 支持连续录入，保存后表单自动清空

### 🎯 秋招雷达 —— 一眼看清「今天该投什么」

把所有岗位收进岗位池后，雷达页帮你快速回答三个问题：**哪些适合我、哪些快截止、哪些该优先处理**。

- 六个互斥快捷筛选：临期、今日新增、本周截止、收藏、高匹配、待评估
- 搜索词 + 筛选条件组合检索，随时一键清除
- 个人画像（届别、学历、城市、方向、技能）驱动的本地规则匹配
- 每条推荐都附带**可解释的匹配理由**，不玩黑盒

### 🚀 投递工作台 —— 从「值得投」到「已投递」

- 区分「待投递」与「已投递」，投递清单一目了然
- 「准备投递」进入岗位检查单：资格、DDL、材料、简历版本
- 系统只负责打开官方投递链接，**提交永远由你在官方渠道完成**

### 📈 申请进度 —— 每份申请走到哪、下一步是什么

- 完整状态流转：待投递 → 已投递 → 测评/笔试 → 面试 → Offer → 已结束
- 事件时间线 + 下一步行动及计划时间
- 按「曾到达阶段」统计的转化漏斗
- 本地日历视图，DDL、事件、下一步一屏看清

### 📧 邮件同步（可选）—— 只读、脱敏、待确认

- 主动触发的**本地只读 IMAP** 同步，扫描收件箱近 7 天、最多 50 封
- 自动生成带**脱敏证据**的待确认 proposal，绝不静默写入
- 只有你逐项确认后，才会落地为正式申请事件；改期、取消、模糊关联一律人工处理

### 🧠 可解释 AI（可选）—— 主动启用才生效

- 粘贴 JD，AI 帮你预填结构化字段
- 单岗位 AI 分析，输出评分 + 理由 + 风险
- 所有 AI 能力默认关闭，只有你主动启用并点击后，才会向已配置的服务发送最小必要字段

### 📦 数据导入导出 —— 你的数据你做主

- CSV / XLSX 批量导入，自动字段映射、去重、来源可追溯
- JSON 全量导出（不含任何密钥与敏感原文）
- 用户触发的 ICS 日历导出，以及本地数据库的隔离恢复

---

## 快速开始

### 环境要求

- **Python 3.11+**
- 操作系统：Windows / macOS / Linux 均可

### 1. 克隆仓库

```bash
git clone https://github.com/deer395/GoodJob-v1.git
cd GoodJob-v1
```

### 2. 安装依赖

```bash
python -m pip install -r manual_capture/requirements.txt
```

### 3. 启动应用

```bash
python -m uvicorn manual_capture.app:app --app-dir . --reload
```

启动后，浏览器访问 👉 **http://127.0.0.1:8000**

首次启动会自动创建本地 SQLite 数据库，并执行 Alembic 迁移，无需额外配置即可开始使用。

### 4.（可选）配置 AI 与邮件同步

复制 `.env.example` 为 `.env`，按需填写：

| 变量 | 说明 |
| --- | --- |
| `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` | OpenAI 兼容的 AI 服务，用于可选的 AI 提取与分析 |
| `IMAP_SERVER` / `IMAP_EMAIL` / `IMAP_PASSWORD` | 本地只读 IMAP 邮件同步（163 邮箱用授权码，非登录密码） |
| `FASTAPI_PORT` | 自定义端口，默认 `8000` |

> AI 与 IMAP 均为**可选能力**。不配置也能正常使用岗位收录、雷达、投递、进度等全部核心功能。

---

## 使用指南（页面导览）

| 页面 | 路径 | 你能做什么 |
| --- | --- | --- |
| 总览 | `/` | 一屏总览当前求职状态 |
| 收录岗位 | `/capture` | 30 秒录入一条新岗位 |
| 秋招雷达 | `/jobs` | 搜索、筛选、收藏、评估岗位 |
| 投递工作台 | `/applications` | 管理待投递与已投递清单 |
| 申请进度 | `/progress` | 追踪阶段、事件、下一步行动 |
| 日历视图 | `/calendar` | 本地可视化 DDL 与关键时间 |
| 个人画像 | `/profile` | 设置届别、学历、城市、方向等 |
| 导入 | `/import` | CSV / XLSX 批量导入岗位 |
| AI 设置 | `/ai-settings` | 配置并启用可选的 AI 服务 |
| 数据管理 | `/data-management` | 导出、备份与恢复本地数据 |
| 邮件同步帮助 | `/email-sync-help` | 配置说明与同步诊断 |

**推荐上手路径**：先设置个人画像 → 收录几批岗位 → 到雷达页筛选出优先级 → 在投递工作台逐个准备并投递 → 在申请进度页持续追踪。

---

## 隐私与安全

- **默认零外部依赖**：岗位与申请管理完全本地运行，不联网、不上传。
- **AI 与 IMAP 均为主动启用的可选能力**，启用前会明确告知哪些数据会离开本机。
- **完整邮件正文不落库**：仅保存标题、发件域名、脱敏摘要与人工核对所需的证据片段。
- **相对时间不猜测**：如「收到邮件后 48 小时」「明晚」等无可靠时间锚点的表述，不会被臆断为绝对 Deadline。
- 不要提交 `.env`、邮箱授权码、API Key、完整邮件正文或本地数据库文件。

---

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端框架 | FastAPI |
| 页面渲染 | Jinja2 服务端渲染 + HTMX 局部刷新 |
| 数据存储 | SQLite + SQLAlchemy + Alembic 迁移 |
| 语言 | Python 3.11+ |

轻量单体架构，无 React / Vue / 前端构建工具，开箱即用。

---

## 项目结构

```
GoodJob-v1/
├── manual_capture/           # 可运行应用
│   ├── app.py                # 主应用与路由
│   ├── ai.py                 # 可解释 AI 能力
│   ├── matching.py           # 本地规则匹配
│   ├── email_processing.py   # 邮件解析与 proposal
│   ├── imap_agent.py         # 本地 IMAP Agent
│   ├── import_routes.py      # CSV/XLSX 导入
│   ├── calendar_routes.py    # ICS 导出
│   ├── templates/            # 页面模板
│   ├── static/               # 样式与脚本
│   └── tests/                # 自动化测试
├── alembic/                  # 数据库迁移
├── docs/                     # 产品文档与决策记录
└── evaluation/               # 评估与 benchmark
```

---

## 测试

```powershell
$env:CAMPUSAI_DB_PATH = "$PWD\pytest_local\campusai.db"
python -m pytest manual_capture/tests -q --basetemp "$PWD\pytest_local\tmp"
```

V1 冻结验收：**112 passed**；重建 20 例真实邮件 benchmark，结果为 **19/19 candidate recall、27/27 required-event coverage、0 Critical Error、0 incorrect Deadline、0 silent auto-confirm**。

---

## 不包含的能力（边界声明）

为了守住「本地、人工确认、最终投递权」的底线，GoodJobAI 明确**不做**这些事：

- ❌ 自动登录招聘平台、自动填写表单或自动提交申请
- ❌ 批量投递、海投，或爬取 BOSS 直聘、牛客、拉勾、智联等受限平台
- ❌ 上传完整邮件、简历、截图、授权码或 API Key
- ❌ 用 AI 编造你并不存在的经历或技能
- ❌ 云同步、多人协作、外部日历同步、自动提醒

---

## 说明

本仓库提供的是**本地运行的源代码**，不是已部署的公共网站。每位使用者 clone 后在自己的电脑启动应用，访问自己的 `http://127.0.0.1:8000`，并拥有独立的本地数据库 —— **你的求职数据，只属于你自己。**

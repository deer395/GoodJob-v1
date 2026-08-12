from __future__ import annotations

import sqlite3
import calendar as calendar_module
import json
import re
import subprocess
import sys
import threading
import shutil
import tempfile
from threading import RLock
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from alembic import command
from alembic.config import Config
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .matching import canonical_tags, configured, evaluate
from .calendar_routes import create_calendar_router
from .import_routes import create_import_router
from .ai import AIUnavailable, EXTRACTION_PROMPT_VERSION, SEMANTIC_PROMPT_VERSION, OpenAIClient, config as ai_config, fingerprint
from .email_processing import PARSER_VERSION, local_email_parse
import os, secrets

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "phase-2-fourth-batch-v1"
SOURCES = ("官网", "BOSS直聘", "牛客", "公众号", "其他")
APPLICATION_STATUSES = ("待投递", "已投递", "测评/笔试", "面试", "Offer", "已结束")
PROGRESS_STATUSES = APPLICATION_STATUSES[1:]
STAGE_EVENT_TYPES = {
    "已投递": ("已投递",),
    "测评/笔试": ("测评通知", "笔试通知", "其他测评"),
    "面试": ("一面", "二面", "三面", "HR面", "其他面试"),
    "Offer": ("Offer",),
    "已结束": ("拒信", "主动放弃", "Offer拒绝", "其他结束"),
}
EVENT_TYPES = tuple(dict.fromkeys(item for values in STAGE_EVENT_TYPES.values() for item in values)) + ("备注", "补充材料", "其他记录")
ADVANCE_TARGETS = {
    "已投递": ("测评/笔试", "面试", "Offer", "已结束"),
    "测评/笔试": ("测评/笔试", "面试", "Offer", "已结束"),
    "面试": ("面试", "Offer", "已结束"),
    "Offer": ("Offer", "已结束"),
}


class JobStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._database_lock = RLock()
        self._restart_marker = Path(self.db_path).with_suffix(".restore-pending.json")
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._database_lock:
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
            finally:
                connection.close()

    def initialize(self) -> None:
        """Upgrade through Alembic, then verify rather than mutating schema at runtime."""
        config = Config(str(BASE_DIR.parent / "alembic.ini"))
        config.set_main_option("script_location", str(BASE_DIR.parent / "alembic"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{Path(self.db_path).resolve().as_posix()}")
        self._backup_before_migration_if_needed(config)
        command.upgrade(config, "head")
        self._verify_schema()
        with self.connection() as conn:
            self._backfill_applied_events(conn)
        self._complete_pending_restart_check()

    def _backup_before_migration_if_needed(self, config: Config) -> None:
        db = Path(self.db_path)
        if not db.exists() or db.stat().st_size == 0:
            return
        try:
            with sqlite3.connect(db) as conn:
                row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone()
                current = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] if row else None
        except sqlite3.Error:
            current = None
        from alembic.script import ScriptDirectory
        if current == ScriptDirectory.from_config(config).get_current_head():
            return
        backup_dir = db.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        shutil.copy2(db, backup_dir / f"before-migration-{datetime.now():%Y%m%d-%H%M%S}.db")

    def _complete_pending_restart_check(self) -> None:
        """Only a fresh application start may mark a replacement restore healthy."""
        if not self._restart_marker.exists():
            return
        try:
            marker = json.loads(self._restart_marker.read_text(encoding="utf-8"))
            self.health_check()
            marker["restart_checked_at"] = datetime.now().isoformat(timespec="seconds")
            marker["status"] = "restart_health_check_passed"
            self._restart_marker.with_suffix(".restore-verified.json").write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
            self._restart_marker.unlink()
        except Exception:
            # Keep the pending marker: the startup must not report recovery success.
            raise RuntimeError("恢复后的启动健康检查未通过；请从恢复前备份回滚")

    def _verify_schema(self) -> None:
        required = {
            "job_postings", "candidate_profiles", "applications", "checklist_items",
            "application_events", "import_batches", "ai_settings", "email_dedup",
            "email_events", "email_event_links", "email_sync_diagnostics", "job_ai_analyses", "alembic_version",
        }
        with self.connection() as conn:
            tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = required - tables
            if missing:
                raise RuntimeError("数据库迁移未完成：" + ", ".join(sorted(missing)))

    def health_check(self) -> None:
        self._verify_schema()
        with self.connection() as conn:
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError("数据库关联完整性检查失败")

    def legacy_initialize(self) -> None:
        """Temporary reference for historic databases; no longer called by the application."""
        if not hasattr(self, "_database_lock"):
            self._database_lock = RLock()
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_postings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    title TEXT NOT NULL,
                    city TEXT NOT NULL,
                    application_url TEXT,
                    salary_range TEXT,
                    department TEXT,
                    description_text TEXT,
                    deadline TEXT,
                    source TEXT NOT NULL DEFAULT '其他'
                        CHECK(source IN ('官网', 'BOSS直聘', '牛客', '公众号', '其他')),
                    note TEXT,
                    status TEXT NOT NULL DEFAULT '待评估',
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    duplicate_confirmed INTEGER NOT NULL DEFAULT 0,
                    match_score INTEGER,
                    match_reasons TEXT,
                    source_import_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS candidate_profiles (
              id INTEGER PRIMARY KEY CHECK(id=1), graduation_year TEXT, degree TEXT, school TEXT,
              major TEXT, target_cities TEXT, target_directions TEXT, target_industries TEXT,
              skills TEXT, constraints TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY, job_id INTEGER UNIQUE NOT NULL, status TEXT NOT NULL, applied_at TEXT, resume_version TEXT, next_action TEXT, next_action_due_at TEXT, notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS checklist_items (id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL, label TEXT NOT NULL, is_completed INTEGER NOT NULL DEFAULT 0, is_predefined INTEGER NOT NULL, sort_order INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
            if "next_action_due_at" not in columns:
                conn.execute("ALTER TABLE applications ADD COLUMN next_action_due_at TEXT")
            conn.execute("""CREATE TABLE IF NOT EXISTS application_events (
                id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL,
                event_type TEXT NOT NULL, event_date TEXT NOT NULL,
                scheduled_at TEXT, action_deadline_at TEXT, description TEXT, created_at TEXT NOT NULL,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            )""")
            job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_postings)").fetchall()}
            if "source_import_id" not in job_columns:
                conn.execute("ALTER TABLE job_postings ADD COLUMN source_import_id INTEGER")
            event_columns = {row["name"] for row in conn.execute("PRAGMA table_info(application_events)").fetchall()}
            if "scheduled_at" not in event_columns:
                conn.execute("ALTER TABLE application_events ADD COLUMN scheduled_at TEXT")
            if "action_deadline_at" not in event_columns:
                conn.execute("ALTER TABLE application_events ADD COLUMN action_deadline_at TEXT")
            conn.execute("""CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, imported_at TEXT NOT NULL,
                total_rows INTEGER NOT NULL, created_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0, updated_count INTEGER NOT NULL DEFAULT 0,
                column_mapping TEXT NOT NULL, default_year TEXT, notes TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_settings (id INTEGER PRIMARY KEY CHECK(id=1), ai_enabled INTEGER NOT NULL DEFAULT 0, extraction_consent_version TEXT, extraction_consented_at TEXT, semantic_consent_version TEXT, semantic_consented_at TEXT, extraction_last_used_at TEXT, semantic_last_used_at TEXT)""")
            setting_columns = {row["name"] for row in conn.execute("PRAGMA table_info(ai_settings)").fetchall()}
            for column in ("extraction_last_used_at", "semantic_last_used_at"):
                if column not in setting_columns:
                    conn.execute(f"ALTER TABLE ai_settings ADD COLUMN {column} TEXT")
            if "enable_email_parsing" not in setting_columns: conn.execute("ALTER TABLE ai_settings ADD COLUMN enable_email_parsing INTEGER NOT NULL DEFAULT 0")
            conn.execute("""CREATE TABLE IF NOT EXISTS email_dedup (id INTEGER PRIMARY KEY, dedup_key TEXT NOT NULL UNIQUE,key_type TEXT NOT NULL,mailbox TEXT NOT NULL DEFAULT 'INBOX',uid TEXT,uid_validity TEXT,message_id TEXT,content_hash TEXT,action TEXT NOT NULL,processed_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS email_events (id INTEGER PRIMARY KEY,dedup_key TEXT NOT NULL UNIQUE,message_id TEXT,sender_domain TEXT,subject TEXT NOT NULL,snippet TEXT NOT NULL,received_at TEXT NOT NULL,category TEXT,summary TEXT,confidence REAL,extracted_company TEXT,extracted_title TEXT,extracted_city TEXT,proposed_application_id INTEGER,proposed_scheduled_at TEXT,proposed_action_deadline_at TEXT,status TEXT NOT NULL DEFAULT 'pending',linked_application_event_id INTEGER,parser_version TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            email_columns = {row["name"] for row in conn.execute("PRAGMA table_info(email_events)").fetchall()}
            if "parse_error" not in email_columns: conn.execute("ALTER TABLE email_events ADD COLUMN parse_error TEXT")
            if "proposed_action_deadline_at" not in email_columns: conn.execute("ALTER TABLE email_events ADD COLUMN proposed_action_deadline_at TEXT")
            if "extracted_city" not in email_columns: conn.execute("ALTER TABLE email_events ADD COLUMN extracted_city TEXT")
            conn.execute("""CREATE TABLE IF NOT EXISTS job_ai_analyses (id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, ai_score INTEGER NOT NULL, reasons TEXT NOT NULL, risks TEXT NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, prompt_version TEXT NOT NULL, input_fingerprint TEXT NOT NULL)""")

    @staticmethod
    def _backfill_applied_events(conn: sqlite3.Connection) -> None:
        conn.execute("""INSERT INTO application_events(application_id,event_type,event_date,description,created_at)
            SELECT a.id,'已投递',a.applied_at,'用户确认已在官方渠道提交申请',a.applied_at
            FROM applications a WHERE a.applied_at IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM application_events e WHERE e.application_id=a.id AND e.event_type='已投递'
            )""")

    @staticmethod
    def normalized(*values: str) -> tuple[str, ...]:
        return tuple((value or "").strip().casefold() for value in values)

    def find_duplicate(self, company: str, title: str, city: str):
        company, title, city = self.normalized(company, title, city)
        with self.connection() as conn:
            return conn.execute(
                """SELECT * FROM job_postings
                   WHERE lower(trim(company))=? AND lower(trim(title))=? AND lower(trim(city))=?""",
                (company, title, city),
            ).fetchone()

    def get(self, job_id: int):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM job_postings WHERE id=?", (job_id,)).fetchone()

    def profile(self):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM candidate_profiles WHERE id=1").fetchone()

    def ai_settings(self):
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO ai_settings(id) VALUES(1)")
            return conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone()

    def save_ai_settings(self, enabled: bool, email_enabled: bool = False) -> None:
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO ai_settings(id) VALUES(1)")
            conn.execute("UPDATE ai_settings SET ai_enabled=?,enable_email_parsing=? WHERE id=1", (int(enabled), int(email_enabled)))

    def pending_email_events(self):
        with self.connection() as conn: return conn.execute("SELECT * FROM email_events WHERE status IN ('pending','parse_failed') ORDER BY received_at DESC,id DESC").fetchall()

    def record_email_sync_diagnostic(self, *, started_at: str, finished_at: str, outcome: str,
                                     diagnostic_category: str, candidate_count: int | None = None,
                                     created_count: int | None = None, deduplicated_count: int | None = None,
                                     parser_enabled: bool = False) -> None:
        """Persist one safe, aggregate-only diagnostic record for the local IMAP run."""
        with self.connection() as conn:
            conn.execute("DELETE FROM email_sync_diagnostics")
            conn.execute(
                """INSERT INTO email_sync_diagnostics
                (started_at,finished_at,outcome,diagnostic_category,scan_mailbox,scan_days,scan_limit,
                 candidate_count,created_count,deduplicated_count,parser_enabled)
                VALUES(?,?,?,?, 'INBOX',7,50,?,?,?,?)""",
                (started_at, finished_at, outcome, diagnostic_category, candidate_count,
                 created_count, deduplicated_count, int(parser_enabled)),
            )

    def latest_email_sync_diagnostic(self):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM email_sync_diagnostics ORDER BY id DESC LIMIT 1").fetchone()

    def has_email_dedup(self, dedup_key: str) -> bool:
        with self.connection() as conn:
            return bool(conn.execute("SELECT 1 FROM email_dedup WHERE dedup_key=?", (dedup_key,)).fetchone())

    def insert_email_event(self, payload: dict) -> bool:
        stamp=datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            if conn.execute("SELECT 1 FROM email_dedup WHERE dedup_key=?", (payload["dedup_key"],)).fetchone(): return False
            conn.execute("INSERT INTO email_events(dedup_key,message_id,sender_domain,subject,snippet,received_at,category,summary,confidence,extracted_company,extracted_title,extracted_city,proposed_application_id,proposed_scheduled_at,proposed_action_deadline_at,status,parser_version,parse_error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (payload["dedup_key"],payload.get("message_id"),payload.get("sender_domain"),payload["subject"][:300],payload["snippet"][:200],payload["received_at"],payload.get("category"),payload.get("summary","")[:30],payload.get("confidence"),payload.get("company","")[:120],payload.get("title","")[:160],payload.get("city","")[:120],payload.get("proposed_application_id"),payload.get("proposed_scheduled_at") or None,payload.get("proposed_action_deadline_at") or None,payload.get("status","pending"),PARSER_VERSION,payload.get("parse_error","")[:80],stamp,stamp))
            conn.execute("INSERT INTO email_dedup(dedup_key,key_type,mailbox,action,processed_at) VALUES(?,?,?,?,?)", (payload["dedup_key"],payload.get("key_type","uid"),payload.get("mailbox","INBOX"),payload.get("status","pending"),stamp)); return True

    def email_event(self, event_id: int):
        with self.connection() as conn: return conn.execute("SELECT * FROM email_events WHERE id=?", (event_id,)).fetchone()

    def update_email_parse(self, event_id: int, parsed=None, error: str = "") -> None:
        stamp=datetime.now().isoformat(timespec="seconds")
        proposal=self.proposed_application(parsed.company, parsed.title) if parsed is not None else None
        with self.connection() as conn:
            if parsed is None:
                conn.execute("UPDATE email_events SET status='parse_failed',parse_error=?,updated_at=? WHERE id=?", (error[:80],stamp,event_id)); return
            conn.execute("UPDATE email_events SET category=?,summary=?,confidence=?,extracted_company=?,extracted_title=?,extracted_city=?,proposed_application_id=?,proposed_scheduled_at=?,proposed_action_deadline_at=?,status='pending',parse_error=NULL,updated_at=? WHERE id=?", (parsed.category,parsed.summary,parsed.confidence,parsed.company,parsed.title,parsed.city,proposal,parsed.scheduled_date or None,parsed.action_deadline or None,stamp,event_id))

    def proposed_application(self, company: str, title: str):
        with self.connection() as conn:
            rows=conn.execute("SELECT a.id,j.company,j.title FROM applications a JOIN job_postings j ON j.id=a.job_id").fetchall()
        matches=[row for row in rows if company and company.casefold() in row['company'].casefold() and title and (title.casefold() in row['title'].casefold() or row['title'].casefold() in title.casefold())]
        return matches[0]['id'] if len(matches)==1 else None

    def exact_email_matches(self, company: str, title: str):
        """Return only unambiguous exact company-and-role Application matches for auto-linking."""
        if not company.strip() or not title.strip():
            return []
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT a.id,j.company,j.title FROM applications a JOIN job_postings j ON j.id=a.job_id "
                "WHERE a.status != '待投递'"
            ).fetchall()
        company_key, title_key = company.strip().casefold(), title.strip().casefold()
        return [row for row in rows if row["company"].strip().casefold() == company_key and row["title"].strip().casefold() == title_key]

    @staticmethod
    def _email_target(category: str) -> tuple[str, str] | None:
        mapping = {
            "笔试": ("测评/笔试", "笔试通知"),
            "面试": ("面试", "其他面试"),
            "Offer": ("Offer", "Offer"),
            "拒信": ("已结束", "拒信"),
        }
        return mapping.get(category)

    def safe_auto_email_match(self, company: str, title: str, category: str) -> int | None:
        """Return one candidate only when its current state can legally advance."""
        target = self._email_target(category)
        matches = self.exact_email_matches(company, title)
        if not target or len(matches) != 1:
            return None
        app = self.application_by_id(matches[0]["id"])
        if not app or target[0] not in ADVANCE_TARGETS.get(app["status"], ()):
            return None
        return int(app["id"])

    def resolve_email_event(self, event_id:int, action:str, application_id:int|None=None, confirm_schedule:bool=False, confirm_action_deadline:bool=False, category_override: str = "", scheduled_override: str = "", action_deadline_override: str = "") -> None:
        with self.connection() as conn:
            event=conn.execute("SELECT * FROM email_events WHERE id=?",(event_id,)).fetchone()
            if not event: raise ValueError("邮件事件不存在")
            if action=='dismissed': conn.execute("UPDATE email_events SET status='dismissed',updated_at=? WHERE id=?",(datetime.now().isoformat(timespec='seconds'),event_id)); return
            existing_link = conn.execute("SELECT 1 FROM email_event_links WHERE email_event_id=?", (event_id,)).fetchone()
            if existing_link or event["linked_application_event_id"]:
                raise ValueError("这封邮件已关联过申请事件，不会重复推进")
            app_id=application_id or event['proposed_application_id']
            app = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone() if app_id else None
            if not app: raise ValueError("请选择有效申请")
            category = category_override.strip() or event['category']
            target = self._email_target(category)
            if not target: raise ValueError("该邮件类型不能创建申请事件")
            status, event_type = target
            if status not in ADVANCE_TARGETS.get(app["status"], ()):
                raise ValueError("当前申请状态不允许由这封邮件推进；请保留待确认后人工处理")
            stamp=datetime.now().isoformat(timespec='seconds'); scheduled=scheduled_override.strip() or (event['proposed_scheduled_at'] if confirm_schedule else None)
            action_deadline=action_deadline_override.strip() or (event['proposed_action_deadline_at'] if confirm_action_deadline else None)
            cursor=conn.execute("INSERT INTO application_events(application_id,event_type,event_date,scheduled_at,action_deadline_at,description,created_at) VALUES(?,?,?,?,?,?,?)",(app_id,event_type,event['received_at'][:10],scheduled,action_deadline,event['summary'] or '来自邮件自动解析',stamp))
            conn.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?",(status,stamp,app_id))
            conn.execute("UPDATE email_events SET category=?,status=?,proposed_application_id=?,linked_application_event_id=?,updated_at=? WHERE id=?",(category,'confirmed' if action=='confirmed' else 'auto_applied',app_id,cursor.lastrowid,stamp,event_id))
            conn.execute("INSERT INTO email_event_links(email_event_id,application_event_id,idempotency_key,created_at) VALUES(?,?,?,?)", (event_id, cursor.lastrowid, f"email-event:{event_id}", stamp))

    def link_email_to_manual_application(self, event_id: int, application_id: int) -> None:
        """Record an explicit user link without inventing a parsed stage/event."""
        with self.connection() as conn:
            conn.execute(
                "UPDATE email_events SET status='linked_manual',proposed_application_id=?,updated_at=? WHERE id=?",
                (application_id, datetime.now().isoformat(timespec="seconds"), event_id),
            )

    def consent_ai(self, capability: str) -> None:
        column = "extraction" if capability == "extraction" else "semantic"
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO ai_settings(id) VALUES(1)")
            conn.execute(f"UPDATE ai_settings SET {column}_consent_version=?, {column}_consented_at=? WHERE id=1", ("v1", datetime.now().isoformat(timespec="seconds")))

    def mark_ai_used(self, capability: str) -> None:
        column = "extraction" if capability == "extraction" else "semantic"
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO ai_settings(id) VALUES(1)")
            conn.execute(f"UPDATE ai_settings SET {column}_last_used_at=? WHERE id=1", (datetime.now().isoformat(timespec="seconds"),))

    def latest_ai_analysis(self, job_id: int):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM job_ai_analyses WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()

    def cached_ai_analysis(self, job_id: int, input_fingerprint: str):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM job_ai_analyses WHERE job_id=? AND input_fingerprint=? AND prompt_version=? ORDER BY id DESC LIMIT 1", (job_id, input_fingerprint, SEMANTIC_PROMPT_VERSION)).fetchone()

    def save_ai_analysis(self, job_id: int, result, input_fingerprint: str) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO job_ai_analyses(job_id,ai_score,reasons,risks,model_name,created_at,prompt_version,input_fingerprint) VALUES(?,?,?,?,?,?,?,?)", (job_id, result.ai_score, json.dumps(result.reasons, ensure_ascii=False), json.dumps(result.risks, ensure_ascii=False), ai_config().model, datetime.now().isoformat(timespec="seconds"), SEMANTIC_PROMPT_VERSION, input_fingerprint))

    def save_profile(self, data: dict[str, str]) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        fields = "graduation_year,degree,school,major,target_cities,target_directions,target_industries,skills,constraints"
        values = [data.get(key, "").strip() for key in fields.split(",")]
        for index, field in enumerate(fields.split(",")):
            if field in {"target_cities", "target_directions", "skills"}:
                values[index] = canonical_tags(values[index])
        with self.connection() as conn:
            conn.execute(f"INSERT INTO candidate_profiles(id,{fields},created_at,updated_at) VALUES(1,{','.join('?'*9)},?,?) ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{item}=excluded.{item}" for item in fields.split(",")) + ",updated_at=excluded.updated_at", values + [stamp, stamp])
        self.recompute_matches()

    def recompute_matches(self) -> None:
        profile = self.profile()
        with self.connection() as conn:
            self.recompute_matches_in_connection(conn, profile)

    def recompute_matches_in_connection(self, conn: sqlite3.Connection, profile=None) -> None:
        if profile is None:
            profile = conn.execute("SELECT * FROM candidate_profiles WHERE id=1").fetchone()
        rows = conn.execute("SELECT * FROM job_postings").fetchall()
        for row in rows:
            score, reasons = evaluate(dict(row), dict(profile) if profile else None)
            conn.execute("UPDATE job_postings SET match_score=?,match_reasons=?,updated_at=? WHERE id=?", (score, reasons, datetime.now().isoformat(timespec="seconds"), row["id"]))

    def list(self, query: str = "", state_filter: str = "all", sort: str = "priority"):
        clauses: list[str] = []
        params: list[str] = []
        if query:
            clauses.append("(company LIKE ? OR title LIKE ? OR city LIKE ? OR department LIKE ?)")
            term = f"%{query}%"
            params.extend((term, term, term, term))
        if state_filter == "pending":
            clauses.append("status = '待评估'")
        elif state_filter == "near":
            clauses.append("deadline <> '' AND date(deadline) BETWEEN date('now') AND date('now', '+3 days')")
        if state_filter == "today": clauses.append("date(created_at)=date('now','localtime')")
        elif state_filter == "week": clauses.append("deadline <> '' AND date(deadline) BETWEEN date('now','localtime') AND date('now','localtime','weekday 0')")
        elif state_filter == "favorite": clauses.append("is_favorite=1")
        elif state_filter == "high": clauses.append("match_score >= 70")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "CASE WHEN deadline <> '' AND date(deadline) < date('now') THEN 1 ELSE 0 END, CASE WHEN match_score IS NULL THEN 1 ELSE 0 END, match_score DESC, CASE WHEN deadline = '' THEN 1 ELSE 0 END, deadline ASC, updated_at DESC"
        if sort == "newest": order = "created_at DESC"
        elif sort == "deadline": order = "CASE WHEN deadline = '' THEN 1 ELSE 0 END, deadline ASC, updated_at DESC"
        with self.connection() as conn:
            rows = conn.execute(
                f"""SELECT * FROM job_postings {where}
                ORDER BY {order}, id DESC""",
                params,
            ).fetchall()
        if state_filter == "expired":
            return [row for row in rows if deadline_state(row["deadline"]) == "expired"]
        return rows

    def create(self, data: dict[str, str]) -> int:
        stamp = datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO job_postings
                (company,title,city,application_url,salary_range,department,description_text,deadline,source,note,status,created_at,updated_at)
                VALUES (:company,:title,:city,:application_url,:salary_range,:department,:description_text,:deadline,:source,:note,'待评估',:stamp,:stamp)""",
                {**data, "stamp": stamp},
            )
            return int(cursor.lastrowid)

    def update(self, job_id: int, data: dict[str, str]) -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE job_postings SET company=:company,title=:title,city=:city,
                application_url=:application_url,salary_range=:salary_range,department=:department,description_text=:description_text,deadline=:deadline,
                source=:source,note=:note,updated_at=:updated_at WHERE id=:id""",
                {**data, "id": job_id, "updated_at": datetime.now().isoformat(timespec="seconds")},
            )
        self.recompute_matches()

    def delete(self, job_id: int) -> None:
        with self.connection() as conn:
            if conn.execute("SELECT 1 FROM applications WHERE job_id=?", (job_id,)).fetchone():
                raise ValueError("该岗位已有申请记录，为保护申请历史不能删除")
            conn.execute("DELETE FROM job_postings WHERE id=?", (job_id,))

    EXPORT_FIELDS = {
        "job_postings": ("id", "company", "title", "city", "application_url", "salary_range", "department", "description_text", "deadline", "source", "note", "status", "is_favorite", "duplicate_confirmed", "match_score", "match_reasons", "source_import_id", "created_at", "updated_at"),
        "candidate_profiles": ("id", "graduation_year", "degree", "school", "major", "target_cities", "target_directions", "target_industries", "skills", "constraints", "created_at", "updated_at"),
        "applications": ("id", "job_id", "status", "applied_at", "resume_version", "next_action", "next_action_due_at", "notes", "created_at", "updated_at"),
        "checklist_items": ("id", "application_id", "label", "is_completed", "is_predefined", "sort_order", "created_at", "updated_at"),
        "application_events": ("id", "application_id", "event_type", "event_date", "scheduled_at", "action_deadline_at", "description", "created_at"),
        "import_batches": ("id", "filename", "imported_at", "total_rows", "created_count", "skipped_count", "updated_count", "column_mapping", "default_year", "notes"),
        "ai_settings": ("id", "ai_enabled", "extraction_consent_version", "extraction_consented_at", "semantic_consent_version", "semantic_consented_at", "extraction_last_used_at", "semantic_last_used_at", "enable_email_parsing"),
        "email_dedup": ("id", "dedup_key", "key_type", "mailbox", "uid", "uid_validity", "content_hash", "action", "processed_at"),
            "email_events": ("id", "dedup_key", "sender_domain", "subject", "snippet", "received_at", "category", "summary", "confidence", "extracted_company", "extracted_title", "extracted_city", "proposed_application_id", "proposed_scheduled_at", "proposed_action_deadline_at", "status", "linked_application_event_id", "parser_version", "parse_error", "created_at", "updated_at"),
        "email_event_links": ("email_event_id", "application_event_id", "idempotency_key", "created_at"),
        "job_ai_analyses": ("id", "job_id", "ai_score", "reasons", "risks", "model_name", "created_at", "prompt_version", "input_fingerprint"),
    }
    EXPORT_TABLES = tuple(EXPORT_FIELDS)

    @staticmethod
    def _redact_export_value(value):
        if not isinstance(value, str):
            return value
        return re.sub(r"(?i)[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", "[已脱敏邮箱]", value)

    def export_snapshot(self) -> dict:
        with self.connection() as conn:
            data = {
                table: [
                    {field: self._redact_export_value(row[field]) for field in fields}
                    for row in conn.execute(f"SELECT {','.join(fields)} FROM {table} ORDER BY rowid").fetchall()
                ]
                for table, fields in self.EXPORT_FIELDS.items()
            }
        return {"format_version": 1, "app_version": APP_VERSION, "exported_at": datetime.now().isoformat(timespec="seconds"), "data": data}

    def restore_snapshot(self, payload: dict) -> Path:
        """Verify into an isolated DB, then replace the entire current local database."""
        if not isinstance(payload, dict) or payload.get("format_version") != 1 or not isinstance(payload.get("data"), dict):
            raise ValueError("恢复文件格式或版本不受支持")
        data = payload["data"]
        if set(data) != set(self.EXPORT_TABLES) or any(not isinstance(data[table], list) for table in self.EXPORT_TABLES):
            raise ValueError("恢复文件缺少必要数据集合")
        db = Path(self.db_path)
        backup_dir = db.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="campusai-restore-", dir=db.parent))
        candidate = temp_dir / "validated.db"
        backup = backup_dir / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.db"
        try:
            isolated = JobStore(candidate)
            with isolated.connection() as conn:
                for table in reversed(self.EXPORT_TABLES):
                    conn.execute(f"DELETE FROM {table}")
                for table in self.EXPORT_TABLES:
                    rows = data[table]
                    if not rows:
                        continue
                    columns = list(self.EXPORT_FIELDS[table])
                    if any(not isinstance(row, dict) or set(row) != set(columns) for row in rows):
                        raise ValueError(f"恢复文件中的 {table} 结构不一致")
                    placeholders = ",".join("?" for _ in columns)
                    conn.executemany(
                        f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
                        [[row[column] for column in columns] for row in rows],
                    )
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise ValueError("恢复文件存在关联关系损坏")
            isolated._verify_schema()
            shutil.copy2(db, backup)
            try:
                os.replace(candidate, db)
                self._restart_marker.write_text(json.dumps({"backup": str(backup), "status": "pending_restart_health_check", "replaced_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False), encoding="utf-8")
            except Exception:
                shutil.copy2(backup, db)
                raise
            return backup
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def toggle_favorite(self, job_id: int) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE job_postings SET is_favorite=1-is_favorite,updated_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), job_id))

    def application(self, job_id: int):
        with self.connection() as conn: return conn.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()

    def application_by_id(self, app_id: int):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()

    def create_application(self, job_id: int) -> int:
        existing = self.application(job_id)
        if existing: return existing["id"]
        stamp = datetime.now().isoformat(timespec="seconds")
        labels = ["确认届别/学历/专业符合 JD 要求", "确认投递截止日期（DDL）未过期", "准备好对应版本的简历（命名清晰）", "打开官方投递链接，检查表单是否完整", "记录投递完成后的下一步行动"]
        job = self.get(job_id)
        if job and deadline_state(job["deadline"]) == "expired": labels[1] = "DDL 已过期，确认仍继续投递"
        if job and not job["application_url"]: labels[3] = "未提供投递链接，请手动核实投递入口"
        with self.connection() as conn:
            cur = conn.execute("INSERT INTO applications(job_id,status,created_at,updated_at) VALUES(?,?,?,?)", (job_id,"待投递",stamp,stamp)); app_id=cur.lastrowid
            conn.executemany("INSERT INTO checklist_items(application_id,label,is_completed,is_predefined,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", [(app_id,label,0,1,i,stamp,stamp) for i,label in enumerate(labels,1)])
            return app_id

    def application_items(self, application_id: int):
        with self.connection() as conn: return conn.execute("SELECT * FROM checklist_items WHERE application_id=? ORDER BY sort_order,id",(application_id,)).fetchall()

    def list_applications(self, status: str):
        with self.connection() as conn: return conn.execute("SELECT a.*,j.company,j.title,j.city,j.deadline,j.source,j.application_url,j.is_favorite,j.match_score FROM applications a JOIN job_postings j ON j.id=a.job_id WHERE a.status=? ORDER BY a.updated_at DESC",(status,)).fetchall()

    def save_application(self, app_id: int, resume_version: str, next_action: str, notes: str, next_action_due_at: str | None = None):
        stamp=datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            due = next_action_due_at.strip() if next_action_due_at is not None else None
            if due is None:
                conn.execute("UPDATE applications SET resume_version=?,next_action=?,notes=?,updated_at=? WHERE id=?",(resume_version.strip(),next_action.strip(),notes.strip(),stamp,app_id))
            else:
                conn.execute("UPDATE applications SET resume_version=?,next_action=?,next_action_due_at=?,notes=?,updated_at=? WHERE id=?",(resume_version.strip(),next_action.strip(),due,notes.strip(),stamp,app_id))
            conn.execute("UPDATE checklist_items SET is_completed=?,updated_at=? WHERE application_id=? AND is_predefined=1 AND sort_order=5",(int(bool(next_action.strip())),stamp,app_id))

    def application_events(self, app_id: int):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM application_events WHERE application_id=? ORDER BY event_date DESC,created_at DESC,id DESC", (app_id,)).fetchall()

    def list_progress_applications(self, status: str = "all"):
        clauses = ["a.status IN ('已投递','测评/笔试','面试','Offer','已结束')"]
        params: list[str] = []
        if status in PROGRESS_STATUSES:
            clauses.append("a.status=?")
            params.append(status)
        with self.connection() as conn:
            return conn.execute(f"""SELECT a.*,j.company,j.title,j.city,j.deadline,j.source,j.application_url,j.match_score,j.match_reasons,
                COALESCE((SELECT MAX(event_date) FROM application_events e WHERE e.application_id=a.id),a.applied_at,a.updated_at) AS latest_event_date
                FROM applications a JOIN job_postings j ON j.id=a.job_id
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE WHEN a.status='已结束' THEN 1 ELSE 0 END, a.next_action_due_at IS NULL, a.next_action_due_at, latest_event_date DESC, a.id DESC""", params).fetchall()

    def progress_counts(self) -> dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute("SELECT status,COUNT(*) AS count FROM applications WHERE status IN ('已投递','测评/笔试','面试','Offer','已结束') GROUP BY status").fetchall()
        counts = {status: 0 for status in PROGRESS_STATUSES}
        counts.update({row["status"]: row["count"] for row in rows})
        counts["all"] = sum(counts.values())
        return counts

    def funnel(self) -> dict[str, int]:
        groups = {
            "已投递": ("已投递",),
            "测评/笔试": STAGE_EVENT_TYPES["测评/笔试"],
            "面试": STAGE_EVENT_TYPES["面试"],
            "Offer": ("Offer",),
        }
        with self.connection() as conn:
            return {
                stage: conn.execute(
                    f"SELECT COUNT(DISTINCT application_id) FROM application_events WHERE event_type IN ({','.join('?' for _ in event_types)})",
                    event_types,
                ).fetchone()[0]
                for stage, event_types in groups.items()
            }

    def progress_calendar(self, year: int, month: int) -> list[dict[str, object]]:
        """Build a local-only calendar projection from existing application data."""
        entries: dict[str, list[dict[str, str]]] = {}

        def add(day_value: str | None, kind: str, label: str, application_id: int) -> None:
            if not day_value:
                return
            try:
                day = date.fromisoformat(day_value[:10]).isoformat()
            except ValueError:
                return
            entries.setdefault(day, []).append({"kind": kind, "label": label, "application_id": str(application_id)})

        for application in self.list_progress_applications():
            label = f"{application['company']} · {application['title']}"
            add(application["deadline"], "deadline", f"DDL · {label}", application["id"])
            add(application["next_action_due_at"], "next-action", f"下一步 · {label}", application["id"])
            for event in self.application_events(application["id"]):
                if event["event_type"] in STAGE_EVENT_TYPES["面试"]:
                    kind = "interview"
                elif event["event_type"] in STAGE_EVENT_TYPES["测评/笔试"]:
                    kind = "assessment"
                elif event["event_type"] == "已投递":
                    kind = "applied"
                else:
                    kind = "event"
                add(event["event_date"], kind, f"{event['event_type']} · {label}", application["id"])
                add(event["scheduled_at"], kind, f"{event['event_type']}安排 · {label}", application["id"])
                add(event["action_deadline_at"], "next-action", f"行动截止 · {label}", application["id"])

        cells: list[dict[str, object]] = []
        for week in calendar_module.Calendar(firstweekday=0).monthdatescalendar(year, month):
            for day in week:
                cells.append({"date": day.isoformat(), "day": day.day, "outside": day.month != month, "events": entries.get(day.isoformat(), [])})
        return cells

    def create_import_batch(self, conn: sqlite3.Connection, filename: str, total_rows: int, mapping: dict[str, str], default_year: str) -> int:
        cursor = conn.execute("""INSERT INTO import_batches(filename,imported_at,total_rows,column_mapping,default_year)
            VALUES(?,?,?,?,?)""", (filename, datetime.now().isoformat(timespec="seconds"), total_rows, json.dumps(mapping, ensure_ascii=False), default_year or None))
        return int(cursor.lastrowid)

    def finish_import_batch(self, conn: sqlite3.Connection, batch_id: int, counts: dict[str, int]) -> None:
        conn.execute("UPDATE import_batches SET created_count=?,skipped_count=?,updated_count=? WHERE id=?", (counts["created"], counts["skipped"], counts["updated"], batch_id))

    def create_from_import(self, conn: sqlite3.Connection, data: dict[str, str], batch_id: int, duplicate_confirmed: bool) -> int:
        stamp = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute("""INSERT INTO job_postings(company,title,city,application_url,salary_range,department,deadline,source,note,status,duplicate_confirmed,source_import_id,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,'待评估',?,?,?,?)""", (data["company"], data["title"], data["city"], data["application_url"], data["salary_range"], data["department"], data["deadline"], data["source"] if data["source"] in SOURCES else "其他", data["note"], int(duplicate_confirmed), batch_id, stamp, stamp))
        return int(cursor.lastrowid)

    def update_from_import(self, conn: sqlite3.Connection, job_id: int, data: dict[str, str], batch_id: int) -> None:
        existing = conn.execute("SELECT * FROM job_postings WHERE id=?", (job_id,)).fetchone()
        if not existing:
            raise ValueError("要覆盖的岗位不存在")
        values = {field: data[field] for field in ("company", "title", "city", "application_url", "salary_range", "deadline", "source") if data[field]}
        if "source" in values and values["source"] not in SOURCES:
            values["source"] = "其他"
        values["source_import_id"] = batch_id
        values["updated_at"] = datetime.now().isoformat(timespec="seconds")
        assignments = ", ".join(f"{field}=?" for field in values)
        conn.execute(f"UPDATE job_postings SET {assignments} WHERE id=?", (*values.values(), job_id))

    def list_import_batches(self):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM import_batches ORDER BY imported_at DESC,id DESC").fetchall()

    def get_import_batch(self, batch_id: int):
        with self.connection() as conn:
            return conn.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()

    def calendar_export_entries(self, scope: str, today: date) -> list[dict[str, str]]:
        with self.connection() as conn:
            deadlines = conn.execute("""SELECT j.id,j.company,j.title,j.deadline FROM job_postings j
                LEFT JOIN applications a ON a.job_id=j.id
                WHERE j.deadline <> '' AND (a.id IS NULL OR a.status='待投递')""").fetchall()
            events = conn.execute("""SELECT e.id,e.scheduled_at,e.action_deadline_at,e.event_type,j.company,j.title FROM application_events e
                JOIN applications a ON a.id=e.application_id JOIN job_postings j ON j.id=a.job_id
                WHERE a.status <> '已结束'
                  AND ((e.event_type IN ('其他测评','一面','二面','三面','HR面','其他面试')
                       AND e.scheduled_at IS NOT NULL AND e.scheduled_at <> '')
                       OR (e.action_deadline_at IS NOT NULL AND e.action_deadline_at <> ''))""").fetchall()
            actions = conn.execute("""SELECT a.id,a.next_action_due_at,j.company,j.title FROM applications a
                JOIN job_postings j ON j.id=a.job_id
                WHERE a.next_action_due_at IS NOT NULL AND a.next_action_due_at <> ''
                  AND a.status <> '已结束'""").fetchall()
        items = []
        for row in deadlines:
            items.append({"source": "deadline", "id": str(row["id"]), "date": row["deadline"][:10], "title": f"DDL：{row['company']} {row['title']}"})
        scheduled_event_types = {"其他测评", "一面", "二面", "三面", "HR面", "其他面试"}
        for row in events:
            if row["scheduled_at"] and row["event_type"] in scheduled_event_types:
                items.append({"source": "event", "id": str(row["id"]), "date": row["scheduled_at"][:10], "title": f"{row['event_type']}：{row['company']} {row['title']}"})
            if row["action_deadline_at"]:
                items.append({"source": "action-deadline", "id": str(row["id"]), "date": row["action_deadline_at"][:10], "title": f"行动截止：{row['company']} {row['title']}"})
        for row in actions:
            items.append({"source": "nextaction", "id": str(row["id"]), "date": row["next_action_due_at"][:10], "title": f"下一步：{row['company']} {row['title']}"})
        if scope == "future":
            items = [item for item in items if item["date"] >= today.isoformat()]
        return sorted(items, key=lambda item: (item["date"], item["source"], item["id"]))

    @staticmethod
    def _default_event_description(target_status: str, event_type: str) -> str:
        return f"状态更新为{target_status}" if event_type not in {"备注", "补充材料", "其他记录"} else event_type

    def _insert_event(self, conn: sqlite3.Connection, app_id: int, event_type: str, event_date: str, description: str = "", scheduled_at: str = "", action_deadline_at: str = "") -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError("无效的事件类型")
        stamp = datetime.now().isoformat(timespec="seconds")
        conn.execute("INSERT INTO application_events(application_id,event_type,event_date,scheduled_at,action_deadline_at,description,created_at) VALUES(?,?,?,?,?,?,?)", (app_id,event_type,event_date,scheduled_at.strip() or None,action_deadline_at.strip() or None,description.strip() or self._default_event_description("当前阶段", event_type),stamp))

    def advance_application(self, app_id: int, target_status: str, event_type: str, event_date: str, description: str = "", scheduled_at: str = "", action_deadline_at: str = "") -> str:
        if target_status not in PROGRESS_STATUSES:
            raise ValueError("无效的目标阶段")
        with self.connection() as conn:
            app = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
            if not app:
                raise ValueError("投递记录不存在")
            if target_status not in ADVANCE_TARGETS.get(app["status"], ()):
                raise ValueError("不能回退到更早阶段")
            if event_type not in STAGE_EVENT_TYPES[target_status]:
                raise ValueError("该事件类型不属于目标阶段")
            self._insert_event(conn, app_id, event_type, event_date, description or self._default_event_description(target_status, event_type), scheduled_at, action_deadline_at)
            if target_status != app["status"]:
                conn.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (target_status,datetime.now().isoformat(timespec="seconds"),app_id))
        return target_status

    def add_application_event(self, app_id: int, event_type: str, event_date: str, description: str = "", scheduled_at: str = "", action_deadline_at: str = "") -> None:
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone():
                raise ValueError("投递记录不存在")
            self._insert_event(conn, app_id, event_type, event_date, description, scheduled_at, action_deadline_at)

    def toggle_item(self, item_id: int):
            with self.connection() as conn: conn.execute("UPDATE checklist_items SET is_completed=1-is_completed,updated_at=? WHERE id=? AND NOT (is_predefined=1 AND sort_order=5)",(datetime.now().isoformat(timespec="seconds"),item_id))

    def add_item(self, app_id:int,label:str):
        if not label.strip(): return
        stamp=datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            order=conn.execute("SELECT COALESCE(MAX(sort_order),5)+1 FROM checklist_items WHERE application_id=?",(app_id,)).fetchone()[0]
            conn.execute("INSERT INTO checklist_items(application_id,label,is_completed,is_predefined,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(app_id,label.strip(),0,0,order,stamp,stamp))

    def delete_item(self,item_id:int):
        with self.connection() as conn: conn.execute("DELETE FROM checklist_items WHERE id=? AND is_predefined=0",(item_id,))

    def confirm_application(self, app_id: int) -> bool:
        with self.connection() as conn:
            app=conn.execute("SELECT * FROM applications WHERE id=?",(app_id,)).fetchone()
            if not app or app["status"] != "待投递": return False
            stamp = datetime.now().isoformat(timespec="seconds")
            conn.execute("UPDATE applications SET status='已投递',applied_at=?,updated_at=? WHERE id=?",(stamp,stamp,app_id))
            self._insert_event(conn, app_id, "已投递", stamp, "用户确认已在官方渠道提交申请")
            return True

    def withdraw_application(self,app_id:int) -> bool:
        with self.connection() as conn:
            app = conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
            if not app or app["status"] != "已投递":
                return False
            conn.execute("UPDATE applications SET status='待投递',applied_at=NULL,updated_at=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),app_id))
            return True

    def create_manual_application(self, data: dict[str,str]) -> int:
        job_id=self.create(data)
        app_id=self.create_application(job_id)
        with self.connection() as conn:
            stamp=datetime.now().isoformat(timespec="seconds")
            conn.execute("UPDATE applications SET status='已投递',applied_at=?,updated_at=? WHERE id=?",(stamp,stamp,app_id))
            self._insert_event(conn, app_id, "已投递", stamp, "用户手动记录已完成投递")
        return app_id


def deadline_state(deadline: str | None) -> str | None:
    if not deadline:
        return None
    try:
        days = (date.fromisoformat(deadline) - date.today()).days
    except ValueError:
        return None
    if days < 0:
        return "expired"
    if days <= 3:
        return "near"
    return None


def deadline_countdown(deadline: str | None) -> str:
    """Return a concise, human-readable deadline reminder for the workspace."""
    if not deadline:
        return "未提供 DDL"
    try:
        days = (date.fromisoformat(deadline) - date.today()).days
    except ValueError:
        return f"DDL：{deadline}"
    if days < 0:
        return f"已逾期 {abs(days)} 天"
    if days == 0:
        return "今日截止"
    return f"{days} 天后截止"


def valid_event_datetime(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False


def friendly_datetime(value: str | None) -> str:
    if not value:
        return "未记录"
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%m-%d %H:%M")
    except ValueError:
        try:
            return date.fromisoformat(value).strftime("%m-%d")
        except ValueError:
            return value


def relative_days(value: str | None) -> str:
    if not value:
        return "未记录"
    try:
        event_day = datetime.fromisoformat(value).date()
    except ValueError:
        try:
            event_day = date.fromisoformat(value)
        except ValueError:
            return ""
    days = (date.today() - event_day).days
    if days == 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{abs(days)} 天{'前' if days > 0 else '后'}"


def stage_progress(status: str) -> int:
    return {"已投递": 1, "测评/笔试": 2, "面试": 3, "Offer": 4, "已结束": 4}.get(status, 0)


def table_deadline(deadline: str | None) -> str:
    if not deadline:
        return "—"
    try:
        target = date.fromisoformat(deadline)
    except ValueError:
        return deadline
    days = (target - date.today()).days
    prefix = target.strftime("%m-%d")
    if days < 0:
        return f"{prefix}, 已逾期"
    if days == 0:
        return f"{prefix}, 今天截止"
    return f"{prefix}, {days} 天后"


def table_deadline_class(deadline: str | None) -> str:
    if not deadline:
        return ""
    try:
        days = (date.fromisoformat(deadline) - date.today()).days
    except ValueError:
        return ""
    return "today" if days == 0 else "expired" if days < 0 else "near" if days <= 3 else ""


def table_current_timing(application, events) -> dict[str, str | bool]:
    """Choose the table's single time column according to the active application stage."""
    status = application["status"]
    if status in {"待投递", "已投递"}:
        return {"label": "投递 DDL", "value": application["deadline"] or "", "kind": "deadline"}
    stage_types = set(STAGE_EVENT_TYPES.get(status, ()))
    candidates: list[tuple[datetime, str, str, str]] = []
    for event in events:
        if event["event_type"] not in stage_types:
            continue
        if event["action_deadline_at"]:
            try:
                candidates.append((datetime.fromisoformat(event["action_deadline_at"]), "行动截止", event["action_deadline_at"], "deadline"))
            except ValueError:
                pass
        if event["scheduled_at"]:
            try:
                candidates.append((datetime.fromisoformat(event["scheduled_at"]), f"{event['event_type']}安排", event["scheduled_at"], "schedule"))
            except ValueError:
                pass
    if candidates:
        future = [item for item in candidates if item[0].date() >= date.today()]
        _, label, value, kind = min(future, key=lambda item: item[0]) if future else max(candidates, key=lambda item: item[0])
        return {"label": label, "value": value, "kind": kind}
    return {"label": "当前节点未记录", "value": "", "kind": ""}


def next_key_milestone(application, events) -> dict[str, str] | None:
    """Return the next confirmed post-application action; never substitute job DDL."""
    candidates: list[tuple[datetime, str, str]] = []
    for event in events:
        if event["action_deadline_at"]:
            try:
                candidates.append((datetime.fromisoformat(event["action_deadline_at"]), "行动截止", event["action_deadline_at"]))
            except ValueError:
                pass
        if event["scheduled_at"]:
            try:
                candidates.append((datetime.fromisoformat(event["scheduled_at"]), f"{event['event_type']}安排", event["scheduled_at"]))
            except ValueError:
                pass
    if application["next_action_due_at"]:
        try:
            candidates.append((datetime.fromisoformat(application["next_action_due_at"]), "下一步计划", application["next_action_due_at"]))
        except ValueError:
            pass
    if not candidates:
        return None
    future = [item for item in candidates if item[0].date() >= date.today()]
    if future:
        _, label, value = min(future, key=lambda item: item[0])
        return {"label": label, "value": value, "overdue": False}
    _, label, value = max(candidates, key=lambda item: item[0])
    return {"label": label, "value": value, "overdue": True}


def city_summary(cities: str | None) -> str:
    parts = [part for part in re.split(r"[、,，;；\s]+", cities or "") if part]
    return f"{parts[0]} +{len(parts) - 1}" if len(parts) > 3 else (cities or "—")


def created_ago(created_at: str | None) -> str:
    if not created_at:
        return ""
    try:
        seconds = max(0, int((datetime.now() - datetime.fromisoformat(created_at)).total_seconds()))
    except ValueError:
        return ""
    if seconds < 60:
        return "刚刚"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    return f"{hours // 24} 天前"


def clean_form(data: dict[str, str]) -> dict[str, str]:
    fields = ("company", "title", "city", "application_url", "salary_range", "department", "description_text", "deadline", "source", "note")
    return {field: (data.get(field) or "").strip() for field in fields}


def should_auto_apply_email(payload: dict, store: JobStore) -> int | None:
    """Decision card 3C: advance only for a high-confidence, uniquely evidenced match."""
    if payload.get("category") in {"其他", "群发广告", "", None}:
        return None
    if payload.get("confidence", 0) < 90:
        return None
    company, title = payload.get("company", ""), payload.get("title", "")
    return store.safe_auto_email_match(company, title, payload.get("category", ""))


def semantic_payload(job: dict, profile: dict) -> dict:
    """Minimum allowlist for direction/skill matching; school is intentionally excluded."""
    return {
        "job": {key: str(job.get(key) or "")[:4000] for key in ("company", "title", "city", "department", "description_text", "note")},
        "candidate": {key: str(profile.get(key) or "")[:500] for key in ("graduation_year", "degree", "major", "target_cities", "target_directions", "skills")},
    }


def create_app(db_path: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="GoodJobAI · 手动收录岗位")
    app.state.store = JobStore(db_path or BASE_DIR / "campusai_manual.db")
    app.state.import_cache = {}
    app.state.ai_client = OpenAIClient()
    app.state.ai_inflight = set()
    app.state.ai_lock = threading.Lock()
    app.state.email_sync_lock = threading.Lock()
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    templates.env.globals["deadline_state"] = deadline_state
    templates.env.globals["deadline_countdown"] = deadline_countdown
    templates.env.globals["created_ago"] = created_ago
    templates.env.globals["friendly_datetime"] = friendly_datetime
    templates.env.globals["relative_days"] = relative_days
    templates.env.globals["stage_progress"] = stage_progress
    templates.env.globals["table_deadline"] = table_deadline
    templates.env.globals["table_deadline_class"] = table_deadline_class
    templates.env.globals["city_summary"] = city_summary

    @app.middleware("http")
    async def product_navigation(request: Request, call_next):
        """Keep the small server-rendered templates discoverable without a base-template rewrite."""
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        if b"</nav>" in body and b'href="/data-management"' not in body:
            body = body.replace(b"</nav>", '<a href="/data-management">数据管理</a></nav>'.encode("utf-8"), 1)
        if b"</body>" in body and b"product_actions.js" not in body:
            body = body.replace(b"</body>", b'<script src="/static/product_actions.js"></script></body>', 1)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return HTMLResponse(body, status_code=response.status_code, headers=headers)
    app.include_router(create_import_router(templates))
    app.include_router(create_calendar_router())

    def render_form(request: Request, *, form=None, errors=None, duplicate=None, editing=None, success=None, ai_message="", ai_prefilled=(), ai_evidence=None, jd_text="", extraction_consent=False):
        settings = request.app.state.store.ai_settings()
        return templates.TemplateResponse(
            request,
            "capture.html",
            {
                "sources": SOURCES, "form": form or {"source": "官网"}, "errors": errors or {},
                "duplicate": duplicate, "editing": editing, "success": success, "ai_configured": ai_config().configured,
                "ai_enabled": bool(settings["ai_enabled"]), "ai_message": ai_message or ("AI 已配置但尚未启用，请在导航栏的“AI 设置”开启。" if ai_config().configured and not settings["ai_enabled"] else ""), "ai_prefilled": ai_prefilled,
                "ai_evidence": ai_evidence or {}, "jd_text": jd_text, "extraction_consent": extraction_consent,
            },
        )

    @app.get("/")
    def capture(request: Request, saved: int | None = None):
        success = None
        if saved:
            job = request.app.state.store.get(saved)
            if job:
                success = job
        return render_form(request, success=success)

    @app.post("/ai/extract")
    def ai_extract(request: Request, jd_text: str = Form(""), confirm_consent: str = Form("")):
        jd_text = jd_text.strip()
        settings = request.app.state.store.ai_settings()
        if not ai_config().configured:
            return render_form(request, jd_text=jd_text, ai_message="AI 尚未配置")
        if not settings["ai_enabled"]:
            return render_form(request, jd_text=jd_text, ai_message="请先在 AI 设置中启用 AI")
        if not jd_text or len(jd_text) > 12000:
            return render_form(request, jd_text=jd_text, ai_message="JD 正文不能为空且最多 12000 字")
        if not settings["extraction_consented_at"] and confirm_consent.lower() not in {"1", "true", "on"}:
            return render_form(request, jd_text=jd_text, extraction_consent=True)
        if not settings["extraction_consented_at"]:
            request.app.state.store.consent_ai("extraction")
        with request.app.state.ai_lock:
            if "extract" in request.app.state.ai_inflight:
                return render_form(request, jd_text=jd_text, ai_message="智能提取正在进行，请勿重复提交")
            request.app.state.ai_inflight.add("extract")
        try:
            result = request.app.state.ai_client.extract(jd_text)
            request.app.state.store.mark_ai_used("extraction")
        except AIUnavailable:
            return render_form(request, jd_text=jd_text, ai_message="智能提取暂不可用，请手动填写。")
        finally:
            with request.app.state.ai_lock: request.app.state.ai_inflight.discard("extract")
        values, evidence = {}, {}
        for field in ("company", "title", "city", "department", "salary_range"):
            item = getattr(result, field); values[field] = item.value or ""; evidence[field] = item.evidence or ""
        item = result.deadline; evidence["deadline"] = item.evidence or ""
        try:
            values["deadline"] = date.fromisoformat(item.value).isoformat() if item.value else ""
        except ValueError:
            values["deadline"] = ""
            if item.evidence: evidence["deadline"] = "需人工确认：" + item.evidence
        evidence["graduation_year"] = getattr(result.graduation_year, "evidence", "") or ""
        message = "可能包含多个岗位，请拆分后分别核对填写。" if result.multiple_roles_detected else "已预填 AI 提取结果；请核对后手动保存。"
        return render_form(request, form={"source": "官网", **values, "description_text": jd_text}, ai_prefilled=tuple(values), ai_evidence=evidence, jd_text=jd_text, ai_message=message)

    @app.post("/jobs")
    def save_job(
        request: Request,
        company: str = Form(""), title: str = Form(""), city: str = Form(""),
        application_url: str = Form(""), salary_range: str = Form(""), department: str = Form(""), description_text: str = Form(""), deadline: str = Form(""),
        source: str = Form("官网"), note: str = Form(""), job_id: int | None = Form(None),
    ):
        data = clean_form(locals())
        errors = {field: "请填写公司名" if field == "company" else "请填写岗位名" if field == "title" else "请填写工作地点"
                  for field in ("company", "title", "city") if not data[field]}
        if source not in SOURCES:
            errors["source"] = "请选择有效来源"
        if len(data["note"]) > 500:
            errors["note"] = "备注最多 500 字"
        if len(data["department"]) > 100:
            errors["department"] = "部门/业务线最多 100 字"
        if deadline:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors["deadline"] = "请输入有效的截止日期"
        if errors:
            return render_form(request, form=data, errors=errors, editing=request.app.state.store.get(job_id) if job_id else None)

        store: JobStore = request.app.state.store
        duplicate = store.find_duplicate(data["company"], data["title"], data["city"])
        if duplicate and duplicate["id"] != job_id:
            return render_form(request, form=data, duplicate=duplicate)
        if job_id:
            if not store.get(job_id):
                raise HTTPException(status_code=404, detail="岗位不存在")
            store.update(job_id, data)
            return RedirectResponse(url=f"/?saved={job_id}", status_code=303)
        created_id = store.create(data)
        store.recompute_matches()
        return RedirectResponse(url=f"/?saved={created_id}", status_code=303)

    @app.get("/jobs")
    def job_pool(request: Request, q: str = "", state: str = "all", sort: str = "priority", deleted: bool = False, delete_error: str = "", imported: int | None = None, updated: int | None = None, skipped: int | None = None, focus: int | None = None):
        state = state if state in {"all", "pending", "near", "expired", "today", "week", "favorite", "high"} else "all"
        store = request.app.state.store
        profile = store.profile()
        profile_configured = configured(dict(profile) if profile else None)
        if state == "high" and not profile_configured: state = "all"
        all_jobs = store.list()
        today = date.today()
        metrics = {
            "total": len(all_jobs),
            "high": sum(job["match_score"] is not None and job["match_score"] >= 70 for job in all_jobs),
            "week": sum(bool(job["deadline"]) and 0 <= (date.fromisoformat(job["deadline"]) - today).days <= 6 for job in all_jobs),
            "favorite": sum(bool(job["is_favorite"]) for job in all_jobs),
        }
        jobs = store.list(q.strip(), state, sort)
        filter_labels = {
            "all": "全部岗位", "pending": "待评估", "near": "临期（未来 3 天）",
            "today": "今日新增", "week": "本周截止", "favorite": "收藏", "high": "高匹配",
            "expired": "已逾期",
        }
        settings = store.ai_settings()
        analyses = {}
        for job in jobs:
            analysis = store.latest_ai_analysis(job["id"])
            if analysis:
                payload = semantic_payload(dict(job), dict(profile) if profile else {})
                analyses[job["id"]] = {**dict(analysis), "reasons": json.loads(analysis["reasons"]), "risks": json.loads(analysis["risks"]), "stale": analysis["input_fingerprint"] != fingerprint(payload, SEMANTIC_PROMPT_VERSION), "payload": payload}
        return templates.TemplateResponse(
            request,
            "pool.html",
            {"jobs": jobs, "q": q.strip(), "state": state, "filter_label": filter_labels[state], "deleted": deleted, "delete_error": delete_error, "imported": imported, "updated": updated, "skipped": skipped, "profile_configured": profile_configured, "profile": profile, "sort": sort, "metrics": metrics, "ai_enabled": bool(settings["ai_enabled"]), "ai_configured": ai_config().configured, "analyses": analyses, "focus": focus},
        )

    @app.get("/email-sync-help")
    def email_sync_help(request: Request):
        configured_fields = {name: bool(os.getenv(name)) for name in ("IMAP_SERVER", "IMAP_EMAIL", "IMAP_PASSWORD", "IMAP_AGENT_TOKEN")}
        return templates.TemplateResponse(request, "email_sync_help.html", {"configured_fields": configured_fields})

    @app.get("/ai-settings")
    def ai_settings_page(request: Request):
        return templates.TemplateResponse(request, "ai_settings.html", {"settings": request.app.state.store.ai_settings(), "ai_configured": ai_config().configured})

    @app.post("/ai-settings")
    def save_ai_settings_route(request: Request, ai_enabled: str = Form(""), enable_email_parsing: str = Form("")):
        request.app.state.store.save_ai_settings(ai_enabled.lower() in {"1", "true", "on"}, enable_email_parsing.lower() in {"1", "true", "on"})
        return RedirectResponse("/ai-settings", status_code=303)

    @app.get("/data-management")
    def data_management(request: Request, message: str = "", error: str = ""):
        return templates.TemplateResponse(request, "data_management.html", {"message": message, "error": error})

    @app.get("/data/export")
    def export_all_data(request: Request):
        body = json.dumps(request.app.state.store.export_snapshot(), ensure_ascii=False, indent=2)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return Response(body, media_type="application/json; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="campusai-export-{stamp}.json"'})

    @app.post("/data/restore")
    async def restore_all_data(request: Request, backup_file: UploadFile = File(...), confirm_replace: str = Form("")):
        if confirm_replace.lower() not in {"true", "1", "on", "yes"}:
            return RedirectResponse("/data-management?error=请确认以全量替换当前本地数据", status_code=303)
        content = await backup_file.read()
        if len(content) > 10 * 1024 * 1024:
            return RedirectResponse("/data-management?error=恢复文件不能超过 10MB", status_code=303)
        try:
            payload = json.loads(content.decode("utf-8"))
            store = request.app.state.store
            with store._database_lock:
                backup = store.restore_snapshot(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OSError, sqlite3.Error) as error:
            return RedirectResponse("/data-management?error=" + str(error), status_code=303)
        return RedirectResponse("/data-management?message=已完成隔离验证并替换数据库；替换前备份：" + str(backup) + "。必须重启应用并通过启动健康检查后，系统才会确认恢复成功。", status_code=303)

    def agent_authorized(request: Request) -> bool:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR.parent / ".env", override=True)
        token=os.getenv("IMAP_AGENT_TOKEN", ""); auth=request.headers.get("authorization", "")
        return bool(token and request.client and request.client.host in {"127.0.0.1", "::1"} and auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], token))

    @app.post("/api/email-events")
    async def ingest_email_event(request: Request):
        if not agent_authorized(request): raise HTTPException(status_code=403, detail="forbidden")
        payload=await request.json()
        required={"dedup_key","subject","snippet","received_at"}
        if not required <= set(payload) or len(payload["snippet"]) > 200: raise HTTPException(status_code=422, detail="invalid event")
        store=request.app.state.store; settings=store.ai_settings()
        # Repeated synchronizations must not trigger paid AI work for an already processed message.
        if store.has_email_dedup(payload["dedup_key"]):
            return {"created": False}
        if settings['enable_email_parsing']:
            try:
                parsed=request.app.state.ai_client.parse_email({'subject':payload['subject'],'sender_domain':payload.get('sender_domain',''),'snippet':payload['snippet']})
                payload.update({'category':parsed.category,'summary':parsed.summary,'confidence':parsed.confidence,'company':parsed.company,'title':parsed.title,'city':parsed.city,'proposed_scheduled_at':parsed.scheduled_date or None,'proposed_action_deadline_at':parsed.action_deadline or None})
                proposal=store.proposed_application(parsed.company,parsed.title); payload['proposed_application_id']=proposal
                auto_application_id = should_auto_apply_email(payload, store)
                if auto_application_id:
                    payload.update({'proposed_application_id': auto_application_id, 'status': 'auto_applied'})
            except AIUnavailable:
                fallback = local_email_parse(payload["subject"], payload["snippet"])
                if fallback:
                    payload.update({'category':fallback.category,'summary':fallback.summary,'confidence':fallback.confidence,'company':fallback.company,'title':fallback.title,'city':fallback.city,'proposed_scheduled_at':fallback.scheduled_date or None,'proposed_action_deadline_at':fallback.action_deadline or None,'status':'pending','parse_error':'AI 解析未完成，已使用本地低置信规则分类，请人工确认'})
                else:
                    # Do not retain provider details or model output; users only need an actionable safe reason.
                    payload.update({'status':'parse_failed','parse_error':'智能解析暂不可用，可稍后主动重新解析'})
        created=store.insert_email_event(payload)
        if created and payload.get('status')=='auto_applied':
            with store.connection() as conn: row=conn.execute('SELECT id FROM email_events WHERE dedup_key=?',(payload['dedup_key'],)).fetchone()
            if row: store.resolve_email_event(row['id'],'auto_applied')
        return {"created": created}

    @app.get("/api/pending-events")
    def pending_email_events(request: Request):
        return [dict(row) for row in request.app.state.store.pending_email_events()]

    @app.post("/api/email-sync")
    def sync_email_once(request: Request):
        """Run the local read-only Agent once, never as a background mailbox watcher."""
        started_at = datetime.now().isoformat(timespec="seconds")
        parser_enabled = bool(request.app.state.store.ai_settings()["enable_email_parsing"])
        if not request.app.state.email_sync_lock.acquire(blocking=False):
            request.app.state.store.record_email_sync_diagnostic(
                started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"),
                outcome="busy", diagnostic_category="busy", parser_enabled=parser_enabled,
            )
            return RedirectResponse("/progress?view=email&message=邮箱同步正在进行，请勿重复点击", status_code=303)
        try:
            result = subprocess.run(
                [sys.executable, str(BASE_DIR / "imap_agent.py"), "--once"],
                cwd=str(BASE_DIR.parent), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                env={**os.environ, "FASTAPI_PORT": str(request.url.port or 8000)},
            )
            diagnostics_match = re.search(r"sync-diagnostics:\s*(\{.*\})", result.stdout)
            diagnostics = json.loads(diagnostics_match.group(1)) if diagnostics_match else None
            if result.returncode == 0:
                count_keys = ("candidate_count", "created_count", "deduplicated_count")
                counts_available = isinstance(diagnostics, dict) and all(
                    isinstance(diagnostics.get(key), int) and not isinstance(diagnostics.get(key), bool)
                    and diagnostics[key] >= 0 for key in count_keys
                )
                if not counts_available:
                    request.app.state.store.record_email_sync_diagnostic(
                        started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"), outcome="failed",
                        diagnostic_category="agent_unavailable", parser_enabled=parser_enabled,
                    )
                    message = "同步未完成：本地 Agent 未提供可验证的结构化统计，计数不可用。请重试或检查本地配置。"
                    return RedirectResponse("/progress?view=email&message=" + message, status_code=303)
                candidate_count = diagnostics["candidate_count"]
                created_count = diagnostics["created_count"]
                deduplicated_count = diagnostics["deduplicated_count"]
                request.app.state.store.record_email_sync_diagnostic(
                    started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"), outcome="success",
                    diagnostic_category="none", candidate_count=candidate_count, created_count=created_count,
                    deduplicated_count=deduplicated_count, parser_enabled=parser_enabled,
                )
                message = f"同步完成：检查到 {candidate_count} 封候选邮件；按 INBOX、近 7 天、最多 50 封扫描，新增 {created_count} 封，去重 {deduplicated_count} 封。"
            else:
                output = (result.stdout or "") + "\n" + (result.stderr or "")
                category = "not_configured" if result.returncode == 2 else "authentication_or_permission" if "auth" in output.lower() or "login" in output.lower() else "connection" if "connect" in output.lower() else "agent_unavailable"
                request.app.state.store.record_email_sync_diagnostic(
                    started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"), outcome="failed",
                    diagnostic_category=category, parser_enabled=parser_enabled,
                )
                message = "同步未完成：本地配置、授权/权限、连接或 Agent 状态需要检查；请重试或查看本地配置说明。"
        except subprocess.TimeoutExpired:
            request.app.state.store.record_email_sync_diagnostic(
                started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"), outcome="timeout",
                diagnostic_category="timeout", parser_enabled=parser_enabled,
            )
            message = "本次同步超时；未创建或修改任何申请。请稍后重试。"
        except OSError:
            request.app.state.store.record_email_sync_diagnostic(
                started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"), outcome="failed",
                diagnostic_category="agent_unavailable", parser_enabled=parser_enabled,
            )
            message = "同步未启动：本地 Python 或邮件 Agent 不可用；计数不可用。请检查本地配置后重试。"
        except (json.JSONDecodeError, ValueError):
            request.app.state.store.record_email_sync_diagnostic(
                started_at=started_at, finished_at=datetime.now().isoformat(timespec="seconds"), outcome="failed",
                diagnostic_category="agent_unavailable", parser_enabled=parser_enabled,
            )
            message = "同步未完成：本地 Agent 未返回可用的统计信息。请重试或查看本地配置说明。"
        finally:
            request.app.state.email_sync_lock.release()
        return RedirectResponse("/progress?view=email&message=" + message, status_code=303)

    @app.post('/api/pending-events/{event_id}/confirm')
    def confirm_pending_event(request: Request,event_id:int,application_id:int=Form(0),confirm_schedule:bool=Form(False),confirm_action_deadline:bool=Form(False)):
        try:
            request.app.state.store.resolve_email_event(event_id,'confirmed',application_id or None,confirm_schedule,confirm_action_deadline)
            message = '邮件已关联，申请阶段已更新'
        except ValueError:
            message = '请先选择一份已投递申请；若尚未记录该投递，请使用“手动补记并关联”'
        return RedirectResponse('/progress?view=email&message='+message,303)
    @app.post('/api/pending-events/{event_id}/relink')
    def relink_pending_event(request: Request,event_id:int,application_id:int=Form(...),confirm_schedule:bool=Form(False),confirm_action_deadline:bool=Form(False)):
        try:
            request.app.state.store.resolve_email_event(event_id,'confirmed',application_id,confirm_schedule,confirm_action_deadline)
            message = '邮件关联已修正，申请阶段已更新'
        except ValueError:
            message = '关联未完成：请先选择一份已投递申请，或手动补记该投递'
        return RedirectResponse('/progress?view=email&message='+message,303)
    @app.post('/api/pending-events/{event_id}/dismiss')
    def dismiss_pending_event(request: Request,event_id:int):
        request.app.state.store.resolve_email_event(event_id,'dismissed'); return RedirectResponse('/progress?message=邮件事件已驳回',303)

    @app.post('/api/pending-events/{event_id}/reparse')
    def reparse_email_event(request: Request, event_id: int):
        store=request.app.state.store; event=store.email_event(event_id); settings=store.ai_settings()
        if not event or event['status'] not in {'pending', 'parse_failed'} or not settings['enable_email_parsing']:
            return RedirectResponse('/progress?view=email&message=当前邮件无法重新解析',303)
        try:
            parsed=request.app.state.ai_client.parse_email({'subject':event['subject'],'sender_domain':event['sender_domain'] or '', 'snippet':event['snippet']})
            store.update_email_parse(event_id, parsed)
            found = []
            if parsed.scheduled_date: found.append(f"候选安排时间 {parsed.scheduled_date}")
            if parsed.action_deadline: found.append(f"候选行动截止 {parsed.action_deadline}")
            message = '邮件已重新解析：' + ('；'.join(found) if found else '未识别到可确认的关键时间，请手动补记')
        except AIUnavailable:
            fallback = local_email_parse(event['subject'], event['snippet'])
            if fallback:
                store.update_email_parse(event_id, fallback)
                found = []
                if fallback.scheduled_date: found.append(f"候选安排时间 {fallback.scheduled_date}")
                if fallback.action_deadline: found.append(f"候选行动截止 {fallback.action_deadline}")
                message = '已使用本地规则重新解析：' + ('；'.join(found) if found else '未识别到可确认的关键时间，请手动补记')
            else:
                store.update_email_parse(event_id, error='AI 服务超时、返回格式不合法或暂不可用')
                message='重新解析暂不可用，请稍后手动重试'
        return RedirectResponse('/progress?view=email&message='+message,303)

    @app.post("/jobs/{job_id}/ai-analyze")
    def ai_analyze(request: Request, job_id: int, confirm_consent: str = Form("")):
        store = request.app.state.store; job = store.get(job_id); profile = store.profile(); settings = store.ai_settings()
        if not job: raise HTTPException(status_code=404, detail="岗位不存在")
        if not (ai_config().configured and settings["ai_enabled"] and configured(dict(profile) if profile else None)):
            return RedirectResponse("/jobs", status_code=303)
        if deadline_state(job["deadline"]) == "expired" or job["match_score"] is None or job["match_score"] >= 80:
            return RedirectResponse("/jobs", status_code=303)
        if not settings["semantic_consented_at"] and confirm_consent.lower() not in {"1", "true", "on"}:
            return RedirectResponse(f"/jobs?focus={job_id}&ai_consent={job_id}", status_code=303)
        if not settings["semantic_consented_at"]: store.consent_ai("semantic")
        payload = semantic_payload(dict(job), dict(profile))
        key = fingerprint(payload, SEMANTIC_PROMPT_VERSION)
        if store.cached_ai_analysis(job_id, key): return RedirectResponse(f"/jobs?focus={job_id}", status_code=303)
        with request.app.state.ai_lock:
            if job_id in request.app.state.ai_inflight: return RedirectResponse("/jobs", status_code=303)
            request.app.state.ai_inflight.add(job_id)
        try:
            result = request.app.state.ai_client.analyze(payload)
            store.save_ai_analysis(job_id, result, key)
            store.mark_ai_used("semantic")
        except AIUnavailable:
            pass
        finally:
            with request.app.state.ai_lock: request.app.state.ai_inflight.discard(job_id)
        return RedirectResponse(f"/jobs?focus={job_id}", status_code=303)

    @app.post("/jobs/{job_id}/favorite")
    def toggle_favorite(request: Request, job_id: int, next_url: str = Form("/jobs")):
        request.app.state.store.toggle_favorite(job_id)
        return RedirectResponse(url=next_url if next_url.startswith("/jobs") else "/jobs", status_code=303)

    @app.post("/jobs/{job_id}/prepare")
    def prepare_application(request: Request, job_id: int):
        app_id=request.app.state.store.create_application(job_id)
        return RedirectResponse(url=f"/applications?focus={app_id}",status_code=303)

    @app.get("/applications")
    def workspace(request: Request, tab: str="pending", focus: int|None=None, message: str="", manual_event: int|None=None):
        store=request.app.state.store; pending=store.list_applications("待投递"); sent=store.list_applications("已投递")
        items={row["id"]:store.application_items(row["id"]) for row in pending+sent}
        event = store.email_event(manual_event) if manual_event else None
        if event and event["status"] not in {"pending", "parse_failed"}: event = None
        return templates.TemplateResponse(request,"applications.html",{"pending":pending,"sent":sent,"items":items,"tab":tab,"focus":focus,"message":message,"manual_event":event})

    @app.post("/applications/{app_id}/save")
    def save_application_route(request: Request, app_id:int, resume_version:str=Form(""), next_action:str=Form(""), notes:str=Form("")):
        request.app.state.store.save_application(app_id,resume_version,next_action,notes); return RedirectResponse(url=f"/applications?focus={app_id}",status_code=303)

    @app.post("/applications/{app_id}/next-action")
    def save_next_action(request:Request,app_id:int,next_action:str=Form("")):
        app=request.app.state.store.application_by_id(app_id)
        if not app:
            raise HTTPException(status_code=404, detail="投递记录不存在")
        request.app.state.store.save_application(app_id,app["resume_version"] or "",next_action,app["notes"] or "")
        return RedirectResponse(url=f"/applications?tab=sent&focus={app_id}&message=下一步行动已保存",status_code=303)

    @app.post("/checklist/{item_id}/toggle")
    def toggle_checklist(request: Request,item_id:int, app_id:int=Form(...)):
        request.app.state.store.toggle_item(item_id); return RedirectResponse(url=f"/applications?focus={app_id}",status_code=303)

    @app.post("/applications/{app_id}/items")
    def add_checklist(request:Request,app_id:int,label:str=Form("")):
        request.app.state.store.add_item(app_id,label); return RedirectResponse(url=f"/applications?focus={app_id}",status_code=303)

    @app.post("/checklist/{item_id}/delete")
    def delete_checklist(request:Request,item_id:int,app_id:int=Form(...)):
        request.app.state.store.delete_item(item_id); return RedirectResponse(url=f"/applications?focus={app_id}",status_code=303)

    @app.post("/applications/{app_id}/confirm")
    def confirm_application_route(request: Request,app_id:int, confirmed:str=Form("false")):
        if confirmed.strip().lower() in {"true", "1", "on", "yes"} and request.app.state.store.confirm_application(app_id): return RedirectResponse(url="/applications?tab=sent&message=已记录投递",status_code=303)
        return RedirectResponse(url=f"/applications?focus={app_id}&message=未能记录投递，请重试",status_code=303)

    @app.post("/applications/{app_id}/withdraw")
    def withdraw_application_route(request:Request,app_id:int,confirmed:str=Form("false")):
        if confirmed.strip().lower() in {"true", "1", "on", "yes"} and request.app.state.store.withdraw_application(app_id):
            return RedirectResponse(url="/applications?message=已撤回至待投递",status_code=303)
        return RedirectResponse(url="/applications?tab=sent&message=仅已投递的记录可撤回",status_code=303)

    @app.post("/applications/manual")
    def manual_application(request:Request,company:str=Form(""),title:str=Form(""),city:str=Form(""),source:str=Form("其他"),application_url:str=Form(""),email_event_id:int|None=Form(None),confirm_schedule:bool=Form(False),confirm_action_deadline:bool=Form(False),event_category:str=Form(""),scheduled_at:str=Form(""),action_deadline_at:str=Form(""),return_to:str=Form("")):
        if not company.strip() or not title.strip() or not city.strip(): return RedirectResponse(url="/applications?message=请填写公司、岗位和地点",status_code=303)
        if (scheduled_at and not valid_event_datetime(scheduled_at)) or (action_deadline_at and not valid_event_datetime(action_deadline_at)):
            return RedirectResponse(url="/progress?view=email&message=请输入有效的安排或行动截止时间",status_code=303)
        store=request.app.state.store
        app_id=store.create_manual_application({"company":company.strip(),"title":title.strip(),"city":city.strip(),"source":source,"application_url":application_url.strip(),"salary_range":"","department":"","description_text":"","deadline":"","note":"手动记录已投递"})
        message = '已手动记录投递'
        if email_event_id:
            event=store.email_event(email_event_id)
            if event and event["status"] == "pending" and event["category"]:
                # The user explicitly chose this email while creating the application.
                store.resolve_email_event(email_event_id, 'confirmed', app_id, confirm_schedule, confirm_action_deadline, event_category, scheduled_at, action_deadline_at)
                message = '已手动记录投递并关联邮件；申请阶段已按该邮件更新'
            elif event and event["status"] == "parse_failed":
                store.link_email_to_manual_application(email_event_id, app_id)
                message = '已手动记录投递并关联邮件；邮件尚未能确定阶段'
        destination = "/progress?view=email&message=" if return_to == "email" else "/applications?tab=sent&message="
        return RedirectResponse(url=destination + message,status_code=303)

    @app.get("/progress")
    def application_progress(request: Request, state: str = "all", view: str = "list", table_sort: str = "priority", year: int | None = None, month: int | None = None, focus: int | None = None, message: str = ""):
        state = state if state in {"all", *PROGRESS_STATUSES} else "all"
        view = view if view in {"list", "table", "calendar", "email"} else "list"
        table_sort = table_sort if table_sort in {"priority", "deadline", "applied"} else "priority"
        today_date = date.today()
        year = year if year and 2000 <= year <= 2100 else today_date.year
        month = month if month and 1 <= month <= 12 else today_date.month
        month_start = date(year, month, 1)
        previous_month = month_start - timedelta(days=1)
        following_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        store = request.app.state.store
        applications = store.list_progress_applications(state)
        event_map = {row["id"]: store.application_events(row["id"]) for row in applications}
        key_milestones = {row["id"]: next_key_milestone(row, event_map[row["id"]]) for row in applications}
        table_timings = {row["id"]: table_current_timing(row, event_map[row["id"]]) for row in applications}
        status_order = {"已投递": 0, "测评/笔试": 1, "面试": 2, "Offer": 3, "已结束": 4}
        def ddl_value(row):
            try: return date.fromisoformat(row["deadline"]) if row["deadline"] else date.max
            except ValueError: return date.max
        if table_sort == "deadline":
            def current_time_value(row):
                value = table_timings[row["id"]]["value"]
                try:
                    return datetime.fromisoformat(value) if "T" in value else datetime.combine(date.fromisoformat(value), datetime.min.time())
                except (TypeError, ValueError):
                    return datetime.max
            table_applications = sorted(applications, key=lambda row: (current_time_value(row), status_order.get(row["status"], 9)))
        elif table_sort == "applied":
            table_applications = sorted(applications, key=lambda row: row["applied_at"] or "", reverse=True)
        else:
            table_applications = sorted(applications, key=lambda row: (status_order.get(row["status"], 9), ddl_value(row), -(row["match_score"] or -1)))
        context = {
            "applications": applications,
            "events": event_map,
            "key_milestones": key_milestones,
            "table_timings": table_timings,
            "table_applications": table_applications,
            "table_sort": table_sort,
            "table_summary": {"total": len(table_applications), "expired": sum(table_deadline_class(row["deadline"]) == "expired" for row in table_applications)},
            "state": state,
            "view": view,
            "counts": store.progress_counts(),
            "funnel": store.funnel(),
            "focus": focus,
            "message": message,
            "today": today_date.isoformat(),
            "stage_event_types": STAGE_EVENT_TYPES,
            "event_types": EVENT_TYPES,
            "advance_targets": ADVANCE_TARGETS,
            "calendar_cells": store.progress_calendar(year, month),
            "calendar_year": year,
            "calendar_month": month,
            "previous_month": previous_month,
            "following_month": following_month,
            "pending_email_events": store.pending_email_events(), "all_applications": store.list_progress_applications(),
            "email_sync_diagnostic": store.latest_email_sync_diagnostic(),
        }
        template = "calendar.html" if view == "calendar" else "progress.html"
        return templates.TemplateResponse(request, template, context)

    @app.post("/progress/{app_id}/advance")
    def advance_progress(request: Request, app_id: int, target_status: str = Form(""), event_type: str = Form(""), event_date: str = Form(""), description: str = Form(""), scheduled_at: str = Form(""), action_deadline_at: str = Form("")):
        if not valid_event_datetime(event_date) or (scheduled_at and not valid_event_datetime(scheduled_at)) or (action_deadline_at and not valid_event_datetime(action_deadline_at)):
            return RedirectResponse(url=f"/progress?focus={app_id}&message=请输入有效的事件日期", status_code=303)
        try:
            target = request.app.state.store.advance_application(app_id, target_status, event_type, event_date, description, scheduled_at, action_deadline_at)
            app = request.app.state.store.application_by_id(app_id)
            job = request.app.state.store.get(app["job_id"]) if app else None
            message = f"已更新：{job['company']} · {job['title']} → {target}" if job else "申请进度已更新"
        except ValueError as error:
            message = str(error)
        return RedirectResponse(url=f"/progress?focus={app_id}&message={message}", status_code=303)

    @app.post("/progress/{app_id}/events")
    def add_progress_event(request: Request, app_id: int, event_type: str = Form(""), event_date: str = Form(""), description: str = Form(""), scheduled_at: str = Form(""), action_deadline_at: str = Form("")):
        if not valid_event_datetime(event_date) or (scheduled_at and not valid_event_datetime(scheduled_at)) or (action_deadline_at and not valid_event_datetime(action_deadline_at)):
            return RedirectResponse(url=f"/progress?focus={app_id}&message=请输入有效的事件日期", status_code=303)
        try:
            request.app.state.store.add_application_event(app_id, event_type, event_date, description, scheduled_at, action_deadline_at)
            message = "事件已添加"
        except ValueError as error:
            message = str(error)
        return RedirectResponse(url=f"/progress?focus={app_id}&message={message}", status_code=303)

    @app.post("/progress/{app_id}/next-action")
    def save_progress_next_action(request: Request, app_id: int, next_action: str = Form(""), next_action_due_at: str = Form("")):
        if next_action_due_at and not valid_event_datetime(next_action_due_at):
            return RedirectResponse(url=f"/progress?focus={app_id}&message=请输入有效的计划时间", status_code=303)
        app = request.app.state.store.application_by_id(app_id)
        if not app:
            raise HTTPException(status_code=404, detail="投递记录不存在")
        request.app.state.store.save_application(app_id, app["resume_version"] or "", next_action, app["notes"] or "", next_action_due_at)
        return RedirectResponse(url=f"/progress?focus={app_id}&message=下一步行动已保存", status_code=303)

    @app.get("/profile")
    def profile_page(request: Request):
        return templates.TemplateResponse(request, "profile.html", {"profile": request.app.state.store.profile() or {}})

    @app.post("/profile")
    def save_profile(request: Request, graduation_year: str = Form(""), degree: str = Form(""), school: str = Form(""), major: str = Form(""), target_cities: str = Form(""), target_directions: str = Form(""), target_industries: str = Form(""), skills: str = Form(""), constraints: str = Form("")):
        request.app.state.store.save_profile(locals())
        return RedirectResponse(url="/jobs", status_code=303)

    @app.get("/jobs/{job_id}/edit")
    def edit_job(request: Request, job_id: int):
        job = request.app.state.store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="岗位不存在")
        return render_form(request, form=dict(job), editing=job)

    @app.get("/api/jobs/{job_id}/delete-info")
    def delete_job_info(request: Request, job_id: int):
        store: JobStore = request.app.state.store
        if not store.get(job_id):
            raise HTTPException(status_code=404, detail="岗位不存在")
        return {"application_count": 1 if store.application(job_id) else 0}

    @app.get("/jobs/{job_id}/delete")
    def delete_job_confirmation(request: Request, job_id: int):
        store: JobStore = request.app.state.store
        job = store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="岗位不存在")
        count = 1 if store.application(job_id) else 0
        blocked = count > 0
        action = "" if blocked else f"<form method='post' action='/jobs/{job_id}/delete'><input type='hidden' name='confirmed' value='true'><button type='submit'>确认删除岗位</button></form>"
        return HTMLResponse(
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>确认删除岗位</title>"
            f"<main><h1>确认删除岗位</h1><p>{job['company']} · {job['title']}</p><p>关联申请数量：{count}</p>"
            + ("<p>为保护申请历史，该岗位不能删除。</p>" if blocked else "<p>删除后无法恢复该岗位记录。请确认。</p>")
            + action + "<p><a href='/jobs'>返回岗位池</a></p></main></html>",
            status_code=409 if blocked else 200,
        )

    @app.post("/jobs/{job_id}/delete")
    def delete_job(request: Request, job_id: int, confirmed: str = Form("")):
        store: JobStore = request.app.state.store
        if not store.get(job_id):
            raise HTTPException(status_code=404, detail="岗位不存在")
        application_count = 1 if store.application(job_id) else 0
        if confirmed.strip().lower() not in {"true", "1", "on", "yes"}:
            return Response(
                "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>需要删除确认</title>"
                f"<main><h1>需要删除确认</h1><p>关联申请数量：{application_count}</p>"
                "<p>未收到服务端确认参数，岗位未删除。</p><p><a href='/jobs'>返回岗位池</a></p></main></html>",
                media_type="text/html; charset=utf-8", status_code=400,
            )
        try:
            store.delete(job_id)
        except ValueError as error:
            return Response(
                f"<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>岗位未删除</title>"
                f"<main><h1>岗位未删除</h1><p>{str(error)}</p><p>关联申请数量：{application_count}</p>"
                "<p>申请、事件和检查项均未修改。</p><p><a href='/progress'>查看关联申请</a> · <a href='/jobs'>返回岗位池</a></p></main></html>",
                media_type="text/html; charset=utf-8",
                status_code=409,
            )
        return RedirectResponse(url="/jobs?deleted=true", status_code=303)

    return app


# Test and maintenance processes may point the import-time application at an isolated local DB.
# Normal launches still use manual_capture/campusai_manual.db.
app = create_app(os.getenv("CAMPUSAI_DB_PATH") or None)

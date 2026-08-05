from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .matching import configured, evaluate

BASE_DIR = Path(__file__).resolve().parent
SOURCES = ("官网", "BOSS直聘", "牛客", "公众号", "其他")


class JobStore:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
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
                    deadline TEXT,
                    source TEXT NOT NULL DEFAULT '其他'
                        CHECK(source IN ('官网', 'BOSS直聘', '牛客', '公众号', '其他')),
                    note TEXT,
                    status TEXT NOT NULL DEFAULT '待评估',
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    duplicate_confirmed INTEGER NOT NULL DEFAULT 0,
                    match_score INTEGER,
                    match_reasons TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS candidate_profiles (
              id INTEGER PRIMARY KEY CHECK(id=1), graduation_year TEXT, degree TEXT, school TEXT,
              major TEXT, target_cities TEXT, target_directions TEXT, target_industries TEXT,
              skills TEXT, constraints TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

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

    def save_profile(self, data: dict[str, str]) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        fields = "graduation_year,degree,school,major,target_cities,target_directions,target_industries,skills,constraints"
        values = [data.get(key, "").strip() for key in fields.split(",")]
        with self.connection() as conn:
            conn.execute(f"INSERT INTO candidate_profiles(id,{fields},created_at,updated_at) VALUES(1,{','.join('?'*9)},?,?) ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{item}=excluded.{item}" for item in fields.split(",")) + ",updated_at=excluded.updated_at", values + [stamp, stamp])
        self.recompute_matches()

    def recompute_matches(self) -> None:
        profile = self.profile()
        with self.connection() as conn:
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
        elif state_filter == "expired":
            clauses.append("deadline <> '' AND date(deadline) < date('now')")
        if state_filter == "today": clauses.append("date(created_at)=date('now','localtime')")
        elif state_filter == "week": clauses.append("deadline <> '' AND date(deadline) BETWEEN date('now','localtime') AND date('now','localtime','weekday 0')")
        elif state_filter == "favorite": clauses.append("is_favorite=1")
        elif state_filter == "high": clauses.append("match_score >= 70")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "CASE WHEN deadline <> '' AND date(deadline) < date('now') THEN 1 ELSE 0 END, CASE WHEN match_score IS NULL THEN 1 ELSE 0 END, match_score DESC, CASE WHEN deadline = '' THEN 1 ELSE 0 END, deadline ASC, updated_at DESC"
        if sort == "newest": order = "created_at DESC"
        elif sort == "deadline": order = "CASE WHEN deadline = '' THEN 1 ELSE 0 END, deadline ASC, updated_at DESC"
        with self.connection() as conn:
            return conn.execute(
                f"""SELECT * FROM job_postings {where}
                ORDER BY {order}, id DESC""",
                params,
            ).fetchall()

    def create(self, data: dict[str, str]) -> int:
        stamp = datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO job_postings
                (company,title,city,application_url,salary_range,department,deadline,source,note,status,created_at,updated_at)
                VALUES (:company,:title,:city,:application_url,:salary_range,:department,:deadline,:source,:note,'待评估',:stamp,:stamp)""",
                {**data, "stamp": stamp},
            )
            return int(cursor.lastrowid)

    def update(self, job_id: int, data: dict[str, str]) -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE job_postings SET company=:company,title=:title,city=:city,
                application_url=:application_url,salary_range=:salary_range,department=:department,deadline=:deadline,
                source=:source,note=:note,updated_at=:updated_at WHERE id=:id""",
                {**data, "id": job_id, "updated_at": datetime.now().isoformat(timespec="seconds")},
            )

    def delete(self, job_id: int) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM job_postings WHERE id=?", (job_id,))

    def toggle_favorite(self, job_id: int) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE job_postings SET is_favorite=1-is_favorite,updated_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), job_id))


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
    fields = ("company", "title", "city", "application_url", "salary_range", "department", "deadline", "source", "note")
    return {field: (data.get(field) or "").strip() for field in fields}


def create_app(db_path: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="CampusAI · 手动收录岗位")
    app.state.store = JobStore(db_path or BASE_DIR / "campusai_manual.db")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    templates.env.globals["deadline_state"] = deadline_state
    templates.env.globals["created_ago"] = created_ago

    def render_form(request: Request, *, form=None, errors=None, duplicate=None, editing=None, success=None):
        return templates.TemplateResponse(
            request,
            "capture.html",
            {
                "sources": SOURCES, "form": form or {"source": "官网"}, "errors": errors or {},
                "duplicate": duplicate, "editing": editing, "success": success,
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

    @app.post("/jobs")
    def save_job(
        request: Request,
        company: str = Form(""), title: str = Form(""), city: str = Form(""),
        application_url: str = Form(""), salary_range: str = Form(""), department: str = Form(""), deadline: str = Form(""),
        source: str = Form("官网"), note: str = Form(""), job_id: int | None = Form(None),
    ):
        data = clean_form(locals())
        errors = {field: "请填写公司名" if field == "company" else "请填写岗位名" if field == "title" else "请填写工作地点"
                  for field in ("company", "title", "city") if not data[field]}
        if source not in SOURCES:
            errors["source"] = "请选择有效来源"
        if len(data["note"]) > 500:
            errors["note"] = "备注最多 500 字"
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
    def job_pool(request: Request, q: str = "", state: str = "all", sort: str = "priority", deleted: bool = False):
        state = state if state in {"all", "pending", "near", "expired", "today", "week", "favorite", "high"} else "all"
        store = request.app.state.store
        profile = store.profile()
        profile_configured = configured(dict(profile) if profile else None)
        if state == "high" and not profile_configured: state = "all"
        return templates.TemplateResponse(
            request,
            "pool.html",
            {"jobs": store.list(q.strip(), state, sort), "q": q.strip(), "state": state, "deleted": deleted, "profile_configured": profile_configured, "profile": profile, "sort": sort},
        )

    @app.post("/jobs/{job_id}/favorite")
    def toggle_favorite(request: Request, job_id: int, next_url: str = Form("/jobs")):
        request.app.state.store.toggle_favorite(job_id)
        return RedirectResponse(url=next_url if next_url.startswith("/jobs") else "/jobs", status_code=303)

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

    @app.post("/jobs/{job_id}/delete")
    def delete_job(request: Request, job_id: int):
        store: JobStore = request.app.state.store
        if not store.get(job_id):
            raise HTTPException(status_code=404, detail="岗位不存在")
        store.delete(job_id)
        return RedirectResponse(url="/jobs?deleted=true", status_code=303)

    return app


app = create_app()

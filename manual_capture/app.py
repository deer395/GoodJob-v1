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
from .matching import canonical_tags, configured, evaluate

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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS candidate_profiles (
              id INTEGER PRIMARY KEY CHECK(id=1), graduation_year TEXT, degree TEXT, school TEXT,
              major TEXT, target_cities TEXT, target_directions TEXT, target_industries TEXT,
              skills TEXT, constraints TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY, job_id INTEGER UNIQUE NOT NULL, status TEXT NOT NULL, applied_at TEXT, resume_version TEXT, next_action TEXT, notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS checklist_items (id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL, label TEXT NOT NULL, is_completed INTEGER NOT NULL DEFAULT 0, is_predefined INTEGER NOT NULL, sort_order INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

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
        for index, field in enumerate(fields.split(",")):
            if field in {"target_cities", "target_directions", "skills"}:
                values[index] = canonical_tags(values[index])
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

    def delete(self, job_id: int) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM job_postings WHERE id=?", (job_id,))

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

    def save_application(self, app_id: int, resume_version: str, next_action: str, notes: str):
        stamp=datetime.now().isoformat(timespec="seconds")
        with self.connection() as conn:
            conn.execute("UPDATE applications SET resume_version=?,next_action=?,notes=?,updated_at=? WHERE id=?",(resume_version.strip(),next_action.strip(),notes.strip(),stamp,app_id))
            conn.execute("UPDATE checklist_items SET is_completed=?,updated_at=? WHERE application_id=? AND is_predefined=1 AND sort_order=5",(int(bool(next_action.strip())),stamp,app_id))

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
            conn.execute("UPDATE applications SET status='已投递',applied_at=?,updated_at=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),datetime.now().isoformat(timespec="seconds"),app_id)); return True

    def withdraw_application(self,app_id:int):
        with self.connection() as conn: conn.execute("UPDATE applications SET status='待投递',applied_at=NULL,updated_at=? WHERE id=?",(datetime.now().isoformat(timespec="seconds"),app_id))

    def create_manual_application(self, data: dict[str,str]) -> int:
        job_id=self.create(data)
        app_id=self.create_application(job_id)
        with self.connection() as conn:
            stamp=datetime.now().isoformat(timespec="seconds")
            conn.execute("UPDATE applications SET status='已投递',applied_at=?,updated_at=? WHERE id=?",(stamp,stamp,app_id))
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


def create_app(db_path: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="GoodJobAI · 手动收录岗位")
    app.state.store = JobStore(db_path or BASE_DIR / "campusai_manual.db")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    templates.env.globals["deadline_state"] = deadline_state
    templates.env.globals["deadline_countdown"] = deadline_countdown
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
    def job_pool(request: Request, q: str = "", state: str = "all", sort: str = "priority", deleted: bool = False):
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
        return templates.TemplateResponse(
            request,
            "pool.html",
            {"jobs": store.list(q.strip(), state, sort), "q": q.strip(), "state": state, "deleted": deleted, "profile_configured": profile_configured, "profile": profile, "sort": sort, "metrics": metrics},
        )

    @app.post("/jobs/{job_id}/favorite")
    def toggle_favorite(request: Request, job_id: int, next_url: str = Form("/jobs")):
        request.app.state.store.toggle_favorite(job_id)
        return RedirectResponse(url=next_url if next_url.startswith("/jobs") else "/jobs", status_code=303)

    @app.post("/jobs/{job_id}/prepare")
    def prepare_application(request: Request, job_id: int):
        app_id=request.app.state.store.create_application(job_id)
        return RedirectResponse(url=f"/applications?focus={app_id}",status_code=303)

    @app.get("/applications")
    def workspace(request: Request, tab: str="pending", focus: int|None=None, message: str=""):
        store=request.app.state.store; pending=store.list_applications("待投递"); sent=store.list_applications("已投递")
        items={row["id"]:store.application_items(row["id"]) for row in pending+sent}
        return templates.TemplateResponse(request,"applications.html",{"pending":pending,"sent":sent,"items":items,"tab":tab,"focus":focus,"message":message})

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
        if confirmed.strip().lower() in {"true", "1", "on", "yes"}: request.app.state.store.withdraw_application(app_id); return RedirectResponse(url="/applications?message=已撤回至待投递",status_code=303)
        return RedirectResponse(url="/applications?tab=sent&message=请确认撤回操作",status_code=303)

    @app.post("/applications/manual")
    def manual_application(request:Request,company:str=Form(""),title:str=Form(""),city:str=Form(""),source:str=Form("其他"),application_url:str=Form("")):
        if not company.strip() or not title.strip() or not city.strip(): return RedirectResponse(url="/applications?message=请填写公司、岗位和地点",status_code=303)
        request.app.state.store.create_manual_application({"company":company.strip(),"title":title.strip(),"city":city.strip(),"source":source,"application_url":application_url.strip(),"salary_range":"","department":"","description_text":"","deadline":"","note":"手动记录已投递"})
        return RedirectResponse(url="/applications?tab=sent&message=已手动记录投递",status_code=303)

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

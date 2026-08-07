"""RFC 5545-compatible local calendar export."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response


def escape_ics(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def create_calendar_router() -> APIRouter:
    router = APIRouter()

    @router.get("/calendar/export")
    def export_calendar(request: Request, scope: str = "future"):
        if scope not in {"future", "all"}:
            raise HTTPException(status_code=400, detail="scope 仅支持 future 或 all")
        today = date.today()
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CampusAI//Calendar//CN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
        for entry in request.app.state.store.calendar_export_entries(scope, today):
            lines.extend(("BEGIN:VEVENT", f"UID:campusai-{entry['source']}-{entry['id']}@localhost", f"DTSTAMP:{now}", f"DTSTART;VALUE=DATE:{entry['date'].replace('-', '')}", f"SUMMARY:{escape_ics(entry['title'])}", "END:VEVENT"))
        lines.append("END:VCALENDAR")
        return Response("\r\n".join(lines) + "\r\n", media_type="text/calendar; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="campusai_calendar.ics"'})

    return router

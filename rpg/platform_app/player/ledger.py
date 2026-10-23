"""Bounded, owner-scoped credit history with server-side search and pagination."""

from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException

from platform_app.db import connect, expose


def history(uid, *, page=1, page_size=10, kind="", query="", date_from=None, date_to=None, before=0):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "开始日期不能晚于结束日期")
    conditions, args = ["l.user_id=%s"], [uid]
    if before:
        conditions.append("l.id<%s")
        args.append(before)
    if kind:
        conditions.append("l.kind=%s")
        args.append(kind)
    if query.strip():
        pattern = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        conditions.append("(l.reason ilike %s or g.title ilike %s or s.title ilike %s)")
        args.extend([pattern] * 3)
    tz = timezone(timedelta(hours=8))
    if date_from:
        conditions.append("l.created_at >= %s")
        args.append(datetime.combine(date_from, time.min, tz))
    if date_to:
        conditions.append("l.created_at <= %s")
        args.append(datetime.combine(date_to, time.max, tz))
    source = """from player_ledger l
        left join player_requests r on r.id=l.request_id
        left join game_saves g on g.id=r.save_id
        left join player_stories s on s.id=g.player_story_id
        where """ + " and ".join(conditions)
    with connect() as db:
        total = db.execute("select count(*) as total " + source, args).fetchone()["total"]
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        rows = db.execute(
            "select l.*,r.charged_micro,g.title as save_title,s.title as story_title "
            + source + " order by l.id desc limit %s offset %s",
            [*args, page_size, (page - 1) * page_size],
        ).fetchall()
    return dict(items=[expose(row) for row in rows], total=total, page=page, page_size=page_size, pages=pages)

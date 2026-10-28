"""Translate internal pipeline events into a small, public progress vocabulary."""

from statistics import median

from platform_app.db import connect

STAGES = {
    "preparing": "正在准备本轮",
    "understanding": "正在理解你的行动",
    "retrieving": "正在整理故事资料",
    "generating": "正在生成剧情",
    "saving": "正在保存剧情与结算积分",
}


def public_stage(name, data):
    phase = data.get("phase")
    if name == "stage":
        phase = {"building_context": "retrieving", "done": "saving"}.get(phase, phase)
    elif name == "agent":
        if isinstance(phase, str) and phase.startswith("provider:"):
            phase = "provider"
        phase = {
            "prompt": "understanding", "intent": "understanding",
            "llm_curator": "understanding", "manifest": "retrieving",
            "provider": "retrieving", "assembly": "retrieving",
            "main_gm": "generating",
        }.get(phase)
        if data.get("phase") == "llm_curator" and data.get("status") == "done":
            phase = "retrieving"
    elif name in {"worldbook_consulting", "worldbook_ready"}:
        phase = "retrieving"
    else:
        return None
    return {"phase": phase, "label": STAGES[phase]} if phase in STAGES else None


def recent_timing(uid, save_id, kind, profile):
    """Use this player's completed turns on this save/model, including state saving."""
    with connect() as db:
        rows = db.execute("""select extract(epoch from (l.created_at-r.created_at)) as seconds
            from player_requests r join player_ledger l on l.request_id=r.id and l.kind='settle'
            where r.user_id=%s and r.save_id=%s and r.kind=%s and r.status='settled'
              and coalesce((r.receipt->>'partial')::boolean,false)=false
              and r.profile->>'api_id'=%s and r.profile->>'model'=%s
              and r.created_at>now()-interval '14 days'
            order by r.created_at desc limit 7""",
            (uid, save_id, kind, profile["api_id"], profile["model"])).fetchall()
    seconds = [float(row["seconds"]) for row in rows if row["seconds"] and row["seconds"] > 0]
    if not seconds:
        return None
    return dict(samples=len(seconds), median_seconds=round(median(seconds)),
                low_seconds=round(min(seconds)), high_seconds=round(max(seconds)))

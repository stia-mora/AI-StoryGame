from __future__ import annotations

from fastapi import HTTPException

from platform_app.db import connect
from platform_app.perms import owns_save

from . import experience


def player_save(uid, sid):
    with connect() as db:
        if not owns_save(db, sid, uid):
            raise HTTPException(404, "找不到此存档")
        save = db.execute("select * from game_saves where id=%s", (sid,)).fetchone()
        if not save.get("player_story_id"):
            raise HTTPException(403, "此存档属于创作工作台")
        return save


def story(story_id, new=False):
    with connect() as db:
        row = db.execute("select * from player_stories where id=%s", (story_id,)).fetchone()
        if not row or (new and row["status"] != "published"):
            raise HTTPException(404, "故事尚未上架")
        if row["status"] == "suspended":
            raise HTTPException(503, "这个故事暂时停止游玩，已保存内容仍可阅读")
        if row.get("authoring_revision_id"):
            edition = db.execute("select r.script_id,r.version,u.display_name,u.username from authoring_revisions r "
                                 "join authoring_projects p on p.id=r.project_id join users u on u.id=p.owner_id where r.id=%s",
                                 (row["authoring_revision_id"],)).fetchone()
            if edition:
                row["script_id"] = edition["script_id"]
                row["author_name"] = edition["display_name"] or edition["username"]
                row["authoring_version"] = edition["version"]
        profile = db.execute(
            "select * from player_model_profiles where id=%s and enabled", (row["profile_id"],)
        ).fetchone()
        if not profile:
            raise HTTPException(503, "故事服务暂时不可用")
        row["profile"] = dict(profile)
        row["profile"].pop("updated_at", None)
        row["profile"]["script_id"] = row["script_id"]
        return row


def public_story(row, *, save_id=None):
    from .character_creation import public_config

    public = {k: row[k] for k in ("id", "title", "introduction", "cover")}
    if public["cover"].startswith("/api/storage/"):
        public["cover"] = f"/api/player/saves/{save_id}/cover" if save_id else f"/api/player/stories/{row['id']}/cover"
    public["identities"] = [
        {k: i[k] for k in ("id", "name", "role", "background", "description", "character_name") if k in i}
        for i in row["identities"]
    ]
    public["martial_soul_creation"] = public_config(row.get("defaults"))
    preview = (row.get("defaults") or {}).get("opening_preview", "")
    if isinstance(preview, str) and preview.strip():
        public["opening_preview"] = preview.strip()[:6000]
    if row.get("author_name"):
        public["author"] = row["author_name"]
        public["version"] = row.get("authoring_version")
    return public


def listed_stories():
    with connect() as db:
        return db.execute("""select p.*,coalesce(u.display_name,u.username) as author_name,r.version as authoring_version
          from player_stories p join player_model_profiles m on m.id=p.profile_id
          left join authoring_revisions r on r.id=p.authoring_revision_id
          left join authoring_projects a on a.id=r.project_id left join users u on u.id=a.owner_id
          where p.status='published' and m.enabled order by p.sort_order,p.id limit 200""").fetchall()


def list_saves(uid, *, page=1, query="", page_size=50):
    """Read only public summary fields; never materialize full save snapshots."""
    query = query.strip()
    predicate = "g.user_id=%s and g.player_story_id is not null"
    params = [uid]
    if query:
        predicate += (" and position(lower(%s) in lower(concat_ws(' ', "
                      "coalesce(g.player_story_snapshot->>'title',p.title),g.title,"
                      "g.state_snapshot#>>'{player,name}'))) > 0")
        params.append(query)
    with connect() as db:
        base = " from game_saves g join player_stories p on p.id=g.player_story_id where " + predicate
        total = db.execute("select count(*) as n" + base, params).fetchone()["n"]
        pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, pages))
        rows = db.execute("""select g.id,g.player_story_id,g.title,g.updated_at,
              coalesce(g.player_story_snapshot->>'title',p.title) as story_title,
              jsonb_build_object('player',jsonb_build_object('name',
                coalesce(g.state_snapshot#>'{player,name}','\"\"'::jsonb)),
                'turn',g.state_snapshot->'turn') as state_snapshot""" + base +
              " order by g.updated_at desc,g.id desc limit %s offset %s",
              (*params, page_size, (page - 1) * page_size)).fetchall()
    return dict(items=[save_summary(row, row["story_title"]) for row in rows], total=total, page=page, pages=pages)


def for_save(save):
    snapshot = save.get("player_story_snapshot")
    if snapshot:
        with connect() as db:
            lifecycle = db.execute("select status from player_stories where id=%s", (save["player_story_id"],)).fetchone()
            if not lifecycle or lifecycle["status"] == "suspended":
                raise HTTPException(503, "这个故事暂时停止游玩，已保存内容仍可阅读")
            profile = db.execute("select * from player_model_profiles where id=%s and enabled", (snapshot["profile_id"],)).fetchone()
        if not profile:
            raise HTTPException(503, "此版本的服务模型暂时不可用")
        selected = dict(snapshot)
        selected["profile"] = dict(profile, script_id=save["script_id"])
        return selected
    return story(save["player_story_id"])


def named_values(values):
    if isinstance(values, dict):
        return [
            {"name": str(name), "description": scalar(item)}
            if not isinstance(item, dict)
            else {"name": str(name), **scalar(item)}
            for name, item in list(values.items())[:100]
        ]
    return scalar(values)


def save_summary(save, title=""):
    title = (save.get("player_story_snapshot") or {}).get("title", title)
    data = save.get("state_snapshot") or {}
    player = data.get("player") or {}
    return dict(
        id=save["id"],
        story_id=save["player_story_id"],
        title=save["title"],
        story_title=title,
        name=player.get("name", ""),
        turn=int(data.get("turn") or 0),
        updated_at=str(save["updated_at"]),
    )


def scalar(value):
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            k: scalar(v)
            for k, v in value.items()
            if k
            in {
                "name",
                "label",
                "text",
                "description",
                "quantity",
                "count",
                "value",
                "level",
                "type",
                "status",
                "relationship",
                "condition",
                "hp",
                "max_hp",
                "ac",
                "role",
                "unit",
                "progress",
            }
        }
    if isinstance(value, list):
        return [scalar(v) for v in value[:100]]
    return ""


def view(uid, sid, before=None, limit=20):
    limit = max(1, min(int(limit), 50))
    from .character_creation import public_setup
    from .turn_updates import milestones, tasks

    save = player_save(uid, sid)
    data = save.get("state_snapshot") or {}
    player = data.get("player") or {}
    world = data.get("world") or {}
    pc = data.get("player_character") or {}
    with connect() as db:
        selected = save.get("player_story_snapshot") or (
            db.execute("select * from player_stories where id=%s", (save["player_story_id"],)).fetchone() or {}
        )
        title = selected.get("title", "")
        # Only the active branch ancestors are readable; raw snapshots and future canon never leave this DTO.
        rows = db.execute(
            f"""with recursive path as (
            select id,parent_id from branch_commits where id=%s and save_id=%s
            union all select c.id,c.parent_id from branch_commits c
            join path p on p.parent_id=c.id where c.save_id=%s)
            select c.id,c.parent_id,c.player_input,c.gm_output,c.turn_index, {experience.snapshot_sql("c.state_snapshot")} as display_state,
                   {experience.snapshot_sql("parent.state_snapshot")} as previous_state
            from path p join branch_commits c on c.id=p.id
            left join branch_commits parent on parent.id=p.parent_id and parent.save_id=%s
            where coalesce(c.gm_output,'')<>'' and (%s::bigint is null or c.id<%s) order by c.id desc limit %s""",
            (save["active_commit_id"], sid, sid, sid, before, before, limit+1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
        receipts = db.execute(
            "select commit_id,receipt from player_requests where user_id=%s and save_id=%s and status='settled' and kind<>'guide' and commit_id=any(%s)",
            (uid, sid, [r["id"] for r in rows]),
        ).fetchall()
    by_commit = {r["commit_id"]: r["receipt"] for r in receipts}
    messages = []
    for row in rows:
        if row["player_input"]:
            messages.append(dict(id=f"{row['id']}-user", role="user", text=row["player_input"]))
        messages.append(
            dict(
                id=f"{row['id']}-gm",
                role="assistant",
                turn=row["turn_index"],
                text=row["gm_output"],
                receipt=by_commit.get(row["id"]),
                progress=experience.progress(
                    row["previous_state"] or {},
                    row["display_state"] or {},
                    row["gm_output"],
                    row["player_input"] or "",
                ),
            )
        )
    current = experience.status(data)
    status = dict(
        name=player.get("name") or pc.get("name") or "",
        role=player.get("role") or pc.get("class") or "",
        location=scalar(current["location"]),
        time=scalar(world.get("time") or ""),
        inventory=scalar(current["inventory"]),
        abilities=scalar(current["abilities"]),
        resources=scalar(current["resources"]),
        people=scalar(current["people"]),
        objective=scalar(current["objective"]),
        attributes=scalar(experience.attributes(data)),
        tasks=tasks(data),
        milestones=milestones(data),
    )
    pending = data.get("pending_action") or {}
    return dict(
        save=save_summary(save, title),
        story=public_story(selected, save_id=sid) if selected else None,
        messages=messages,
        history_before=rows[0]["id"] if has_more and rows else None,
        status=status,
        options=experience.choices(data, narration=rows[-1]["gm_output"] if rows else ""),
        latest_progress=next(
            (m["progress"] for m in reversed(messages) if m["role"] == "assistant"), None
        ),
        journey=[
            dict(
                turn=r["turn_index"],
                message_id=m["id"],
                summary=m["progress"]["summary"],
                changes=m["progress"]["changes"],
                gains=m["progress"]["gains"],
                losses=m["progress"]["losses"],
                events=m["progress"]["events"],
            )
            for r, m in zip(rows, [m for m in messages if m["role"] == "assistant"], strict=True)
        ][-8:],
        has_opening=bool(messages),
        character_setup=public_setup(data),
        pending_action={"id": pending.get("id"), "message": pending.get("message")}
        if pending
        else None,
    )


def require_metered_legacy(uid, sid=None):
    """Also protects creator accounts calling legacy generation on a managed save."""
    if not uid:
        return
    from platform_app import runtime
    from platform_app.player.meter import current

    if not sid:
        sid = (runtime.read_runtime(user_id=uid) or {}).get("save_id")
    if not sid:
        return
    with connect() as db:
        managed = db.execute(
            "select player_story_id from game_saves where id=%s and user_id=%s", (sid, uid)
        ).fetchone()
    if managed and managed.get("player_story_id"):
        run = current(uid)
        if not run or run.save_id != sid:
            raise HTTPException(403, "玩家存档请通过 /play 计费入口继续")

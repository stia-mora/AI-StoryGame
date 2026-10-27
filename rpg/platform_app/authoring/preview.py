"""Version-bound player sessions and durable metered preview execution."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from platform_app.db import connect
from platform_app.player import catalog, wallet

from . import service

TASKS = set()


def story_values(row):
    body = row["contract"]
    play = body["play"]
    world = body["sources"]
    chapters = {ch["key"]: ch for source in world for ch in source["chapters"]}
    openings = {o["key"]: o for o in play["openings"]}
    with connect() as db:
        cards = db.execute("select id,metadata from character_cards where script_id=%s and enabled", (row["script_id"],)).fetchall()
    bindings = {(c["metadata"] or {}).get("authoring_subject"): c["id"] for c in cards}
    identities = []
    for identity in play["identities"]:
        opening = openings[identity["opening"]]
        identities.append({k: v for k, v in identity.items() if k in ("id", "name", "character_name", "role", "background") and v is not None} | {
            "subject": identity.get("subject"), "card_id": bindings.get(identity.get("subject")),
            "birthpoint": dict(chapter_min=chapters[opening["chapter"]]["index"],
                               chapter_max=chapters[opening["chapter"]]["index"],
                               story_time_label=opening["moment"], location=opening["location"]),
        })
    defaults = {k: play[k] for k in ("story_intent", "player_origin", "identity_known") if k in play}
    if defaults.get("player_origin") == "transmigrator":
        # The existing runtime uses "soul" for the generic transmigrator mode.
        defaults["player_origin"] = "soul"
    return dict(title=play["title"], introduction=play["introduction"], cover=play.get("cover", ""), identities=identities, defaults=defaults)


def create(uid, revision_id, identity_id, request_id, name="旅人"):
    request_id = str(uuid.UUID(request_id))
    with wallet.idle_account(uid):
        with connect() as db:
            row = service.revision(db, uid, revision_id)
            old = db.execute("select * from game_saves where user_id=%s and authoring_preview_key=%s", (uid, request_id)).fetchone()
            if old:
                creation = (old.get("player_story_snapshot") or {}).get("preview_creation")
                if old["authoring_revision_id"] != revision_id or creation != dict(identity_id=identity_id, name=name):
                    raise HTTPException(409, "建档请求已用于其他版本")
                return dict(save_id=old["id"], url=f"/play/saves/{old['id']}", reused=True)
            config = db.execute("select value from app_config where key='authoring'").fetchone()
            pid = ((config or {}).get("value") or {}).get("preview_profile_id")
            if not pid or not db.execute("select 1 from player_model_profiles where id=%s and enabled", (pid,)).fetchone():
                raise HTTPException(503, "管理员尚未配置可用的试玩服务模型")
            values = story_values(row)
            if identity_id not in {i["id"] for i in values["identities"]}:
                raise HTTPException(400, "此版本不存在该身份")
            story = db.execute("select * from player_stories where script_id=%s", (row["script_id"],)).fetchone()
            if not story:
                story = db.execute("""insert into player_stories(script_id,profile_id,title,introduction,cover,identities,defaults,
                  authoring_project_id,authoring_revision_id) values(%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
                  (row["script_id"], pid, values["title"], values["introduction"], values["cover"], Jsonb(values["identities"]),
                   Jsonb(values["defaults"]), row["project_id"], row["id"])).fetchone()
            selected = dict(story) | values | dict(script_id=row["script_id"], profile_id=pid)
            user = dict(service.creator(db, uid))
        from platform_app.api.player import Create, _create
        result = _create(Create(story_id=story["id"], identity_id=identity_id, name=name), user,
                         selected=selected, preview_revision=revision_id, preview_key=request_id)
        sid = result["save"]["id"]
    return dict(save_id=sid, url=f"/play/saves/{sid}", reused=False)


def owned_save(uid, sid, revision_id):
    with connect() as db:
        service.revision(db, uid, revision_id)
    save = catalog.player_save(uid, sid)
    if save.get("authoring_revision_id") != revision_id:
        raise HTTPException(404, "试玩不属于此版本")
    return save


def quote(uid, revision_id, save_id, kind, message="", reveal_future=False):
    owned_save(uid, save_id, revision_id)
    from platform_app.api.player import Quote
    from platform_app.api.player import quote as player_quote
    return player_quote(Quote(save_id=save_id, kind=kind, message=message, reveal_future=reveal_future), user={"id": uid})


async def execute(uid, revision_id, save_id, kind, message, quote_id, request_id, cap_micro, reveal_future=False, credential=None):
    owned_save(uid, save_id, revision_id)
    request_id = str(uuid.UUID(request_id))
    quote_id = str(uuid.UUID(quote_id))
    with connect() as db:
        user = dict(service.creator(db, uid))
        row = db.execute("select * from player_quotes where id=%s and user_id=%s and save_id=%s and funding='preview'",
                         (quote_id, uid, save_id)).fetchone()
        if not row or cap_micro != row["cap_micro"]:
            raise HTTPException(409, "请确认该试玩报价的费用上限")
        revision = service.revision(db, uid, revision_id)
        old = db.execute("select * from authoring_jobs where id=%s", (request_id,)).fetchone()
        job_input = dict(save_id=save_id, quote_id=quote_id, kind=kind, message=message, revision_id=revision_id, reveal_future=reveal_future)
        if old:
            if old["owner_id"] != uid or old["input"] != job_input:
                raise HTTPException(409, "请求编号已用于其他试玩行动")
            return dict(job_id=request_id, reused=True)
        inserted = db.execute("insert into authoring_jobs(id,project_id,owner_id,kind,input) values(%s,%s,%s,'preview',%s) "
                              "on conflict(id) do nothing returning id", (request_id, revision["project_id"], uid, Jsonb(job_input))).fetchone()
        if not inserted:
            old = db.execute("select * from authoring_jobs where id=%s", (request_id,)).fetchone()
            if old["owner_id"] != uid or old["input"] != job_input:
                raise HTTPException(409, "请求编号已用于其他试玩行动")
            return dict(job_id=request_id, reused=True)
    from platform_app.api.player import Execute
    args = Execute(save_id=save_id, kind=kind, message=message, quote_id=quote_id, request_id=request_id,
                   action_id=request_id, reveal_future=reveal_future)
    async def run():
        from .oauth import check_credential
        try:
            with connect() as db:
                check_credential(db, uid, credential, "authoring:preview")
                db.execute("update authoring_jobs set status='running' where id=%s", (request_id,))
            from platform_app.api.player import execute as player_execute
            from platform_app.api.player import request_status
            response = await player_execute(args, user=user)
            async for _ in response.body_iterator:
                pass
            status = request_status(uuid.UUID(request_id), user=user)
            with connect() as db:
                db.execute("update authoring_jobs set status=%s,result=%s,error=%s,progress=100 where id=%s",
                           ("succeeded" if status["status"] == "settled" else "failed", Jsonb(status), status.get("reason", ""), request_id))
        except Exception as exc:
            wallet.release(uid, request_id, "试玩执行失败")
            with connect() as db:
                db.execute("update authoring_jobs set status='failed',error=%s where id=%s",
                           (str(exc.detail if isinstance(exc, HTTPException) else "试玩执行失败")[:500], request_id))
    task = asyncio.create_task(run())
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return dict(job_id=request_id, reused=False)


def reconcile():
    # A process restart must not repeat model calls. Receipts remain authoritative.
    wallet.reap()
    with connect() as db:
        db.execute("delete from authoring_uploads where id in (select u.id from authoring_uploads u "
                   "where u.created_at<now()-interval '24 hours' and not exists(select 1 from authoring_jobs j "
                   "where j.kind='import' and j.status in ('pending','running') and j.input->>'upload_id'=u.id::text) limit 100)")
        db.execute("""update authoring_jobs j set status=case when r.status='settled' then 'succeeded' else 'failed' end,
          result=jsonb_build_object('status',r.status,'receipt',r.receipt),error=r.reason
          from player_requests r where j.id=r.id and j.kind='preview' and j.status in ('pending','running')
          and r.status in ('settled','released')""")
        db.execute("""update authoring_jobs j set status='failed',error='进程中断，未启动的试玩可重新报价'
          where kind='preview' and status in ('pending','running') and created_at<now()-interval '5 minutes'
          and not exists(select 1 from player_requests r where r.id=j.id)""")

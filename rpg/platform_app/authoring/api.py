"""Browser and upload entry points; business logic is shared with MCP."""
from __future__ import annotations

import base64
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb

from platform_app.db import connect, expose
from platform_app.player import wallet

from . import oauth, preview, service
from .contract import CHUNK_BYTES, get_contract

router = APIRouter()
SCOPES = dict(create_project="write", begin_upload="write", upload_chunk="write", complete_upload="write",
              validate_package="write", import_draft="write", get_job="read", get_draft="read", submit="submit")


@router.get("/api/authoring")
def dashboard(request: Request):
    user = oauth.request_user(request)
    balance = wallet.preview_wallet(user["id"])
    with connect() as db:
        projects = db.execute("select * from authoring_projects where owner_id=%s order by created_at desc limit 100", (user["id"],)).fetchall()
        ledger = db.execute("select id,kind,preview_delta,preview_held_delta,reason,created_at from player_ledger "
                            "where user_id=%s and (preview_delta<>0 or preview_held_delta<>0) order by id desc limit 30", (user["id"],)).fetchall()
    return dict(projects=[expose(p) for p in projects], wallet=balance, author=user.get("display_name") or user["username"],
                ledger=[expose(row) for row in ledger], endpoint=oauth.resource(), scopes=oauth.SCOPES)


@router.get("/api/authoring/contract")
def contract(request: Request, section: str = "summary"):
    oauth.request_user(request)
    return get_contract(section)


@router.post("/api/authoring/action/{action}")
async def action(action: str, request: Request):
    if action not in SCOPES and action not in ("review", "preview", "redeem"):
        raise HTTPException(404, "操作不存在")
    scope = "authoring:" + SCOPES.get(action, "preview" if action in ("preview", "redeem") else "submit")
    user = oauth.request_user(request, scope)
    data = await request.json()
    if action == "review":
        # Package data and external write tokens cannot impersonate browser review.
        user = oauth.session_user(request)
        return service.review(user["id"], int(data["revision_id"]), str(data["rights_note"]))
    if action == "redeem":
        return wallet.redeem(user["id"], str(data["code"]))
    if action == "preview":
        return await preview_action(user, data)
    if action == "import_draft":
        data["credential"] = user.get("_credential")
    import asyncio
    return await asyncio.to_thread(getattr(service, action), user["id"], **data)


async def preview_action(user, data):
    data = dict(data)
    mode = data.pop("mode")
    if mode == "create":
        import asyncio
        return await asyncio.to_thread(preview.create, user["id"], **data)
    if mode == "quote":
        import asyncio
        return await asyncio.to_thread(preview.quote, user["id"], **data)
    if mode == "execute":
        return await preview.execute(user["id"], credential=user.get("_credential"), **data)
    raise HTTPException(400, "试玩模式无效")


@router.put("/api/authoring/uploads/{upload_id}/content")
async def upload_content(upload_id: uuid.UUID, request: Request):
    user = oauth.request_user(request, "authoring:write")
    with connect() as db:
        total = service.upload(db, user["id"], upload_id)["size"]
    buffer, part, received = bytearray(), 0, 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > total:
            raise HTTPException(413, "超过上传大小")
        buffer.extend(chunk)
        while len(buffer) >= CHUNK_BYTES:
            service.upload_chunk(user["id"], upload_id, part, base64.b64encode(buffer[:CHUNK_BYTES]).decode())
            del buffer[:CHUNK_BYTES]
            part += 1
    if buffer:
        service.upload_chunk(user["id"], upload_id, part, base64.b64encode(buffer).decode())
    return service.complete_upload(user["id"], upload_id)


@router.get("/api/storage/authoring/{uid}/{filename}")
def private_cover(uid: int, filename: str, request: Request):
    user = oauth.request_user(request)
    if uid != user["id"] or Path(filename).suffix not in (".png", ".jpg", ".webp"):
        raise HTTPException(404)
    from platform_app.storage import resolve_path
    path = resolve_path(f"authoring/{uid}/{filename}")
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


def admin_user(request):
    user = oauth.session_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


@router.get("/api/authoring/admin")
def admin_dashboard(request: Request):
    admin_user(request)
    with connect() as db:
        config = db.execute("select value from app_config where key='authoring'").fetchone()
        rows = db.execute("""select s.*,p.title,u.username,r.version,r.rights_note,r.report from authoring_submissions s
          join authoring_revisions r on r.id=s.revision_id join authoring_projects p on p.id=r.project_id
          join users u on u.id=p.owner_id order by s.created_at desc limit 100""").fetchall()
        profiles = db.execute("select id,name,enabled from player_model_profiles order by id").fetchall()
    return dict(config=(config or {}).get("value") or {}, submissions=[expose(row) for row in rows], profiles=[expose(p) for p in profiles])


@router.get("/api/authoring/admin/submissions/{submission_id}")
def inspect_submission(submission_id: uuid.UUID, request: Request, offset: int = 0):
    admin_user(request)
    if not 0 <= offset <= 10000:
        raise HTTPException(400, "分页位置无效")
    with connect() as db:
        row = db.execute("select r.* from authoring_revisions r join authoring_submissions s on s.revision_id=r.id where s.id=%s", (submission_id,)).fetchone()
        if not row:
            raise HTTPException(404, "申请不存在")
        chapters = db.execute("select chapter_index,title,content from script_chapters where script_id=%s order by chapter_index limit 10 offset %s", (row["script_id"], offset)).fetchall()
        playtests = db.execute("select id,status,result,error from authoring_jobs where kind='preview' and project_id=%s "
                              "and input->>'revision_id'=%s order by created_at desc limit 20", (row["project_id"], str(row["id"]))).fetchall()
    return dict(contract=row["contract"], chapters=[expose(c) for c in chapters], offset=offset,
                playtests=[expose(p) for p in playtests])


@router.post("/api/authoring/admin")
async def administer(request: Request):
    admin = admin_user(request)
    data = await request.json()
    with connect() as db:
        from platform_app.api.admin._shared import _write_audit
        pid = data.get("profile_id")
        if pid and not db.execute("select id from player_model_profiles where id=%s and enabled", (pid,)).fetchone():
            raise HTTPException(400, "服务模型不可用")
        if data.get("action") == "configure":
            if not pid:
                raise HTTPException(400, "请选择试玩模型")
            db.execute("insert into app_config(key,value) values('authoring',%s) on conflict(key) do update set value=excluded.value",
                       (Jsonb(dict(preview_profile_id=int(pid))),))
        else:
            submission = db.execute("select * from authoring_submissions where id=%s for update", (uuid.UUID(data["submission_id"]),)).fetchone()
            if not submission:
                raise HTTPException(409, "申请已处理或不存在")
            revision = db.execute("select * from authoring_revisions where id=%s", (submission["revision_id"],)).fetchone()
            owner = db.execute("select * from authoring_projects where id=%s for update", (revision["project_id"],)).fetchone()
            if data.get("action") == "suspend":
                if not owner["published_story_id"] or not str(data.get("reason", "")).strip():
                    raise HTTPException(400, "请提供暂停原因")
                db.execute("update player_stories set status='suspended' where id=%s", (owner["published_story_id"],))
                _write_audit(db, admin, "authoring.suspend", "story", str(owner["published_story_id"]), {"reason": str(data["reason"])[:2000]})
                return dict(ok=True)
            if submission["status"] != "pending_review":
                raise HTTPException(409, "申请已处理")
            service.creator(db, owner["owner_id"])
            if data.get("action") == "approve":
                if not pid or not revision["reviewed_at"] or not revision["rights_note"]:
                    raise HTTPException(409, "需要作者复核及有效服务模型")
                from platform_app.workspace.listing import _readiness_for_scripts
                ready = _readiness_for_scripts(db, [revision["script_id"]])[revision["script_id"]]
                if {"chunks", "canon"} & set(ready["missing"]):
                    raise HTTPException(409, "章节或世界资料尚未准备完成")
                values = preview.story_values(revision)
                main = db.execute("select * from player_stories where id=%s", (owner["published_story_id"],)).fetchone() if owner["published_story_id"] else None
                if not main:
                    main = db.execute("select * from player_stories where script_id=%s", (revision["script_id"],)).fetchone()
                if not main:
                    main = db.execute("insert into player_stories(script_id,profile_id,title,authoring_project_id) values(%s,%s,%s,%s) returning *",
                                      (revision["script_id"], pid, values["title"], revision["project_id"])).fetchone()
                # Keep the public story ID (and comments); editions resolve through the revision pointer.
                db.execute("""update player_stories set profile_id=%s,title=%s,introduction=%s,cover=%s,identities=%s,defaults=%s,
                  authoring_revision_id=%s,status='published',updated_at=now() where id=%s""",
                           (pid, values["title"], values["introduction"], values["cover"], Jsonb(values["identities"]), Jsonb(values["defaults"]), revision["id"], main["id"]))
                db.execute("update authoring_projects set published_story_id=%s where id=%s", (main["id"], revision["project_id"]))
                status = "published"
            elif data.get("action") == "reject" and str(data.get("reason", "")).strip():
                status = "rejected"
            else:
                raise HTTPException(400, "操作无效或缺少拒绝原因")
            db.execute("update authoring_submissions set status=%s,reason=%s,reviewed_at=now() where id=%s",
                       (status, str(data.get("reason", ""))[:2000], submission["id"]))
        _write_audit(db, admin, "authoring."+str(data.get("action")), "authoring", str(data.get("submission_id", "settings")))
    return dict(ok=True)

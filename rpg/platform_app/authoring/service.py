"""Owned projects, bounded uploads and durable atomic imports."""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from platform_app import federation
from platform_app.db import connect, expose

from .contract import CHUNK_BYTES, inspect_package

log = logging.getLogger(__name__)
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="authoring")


def creator(db, uid):
    user = db.execute("select * from users where id=%s", (uid,)).fetchone()
    if not user or user.get("deactivated_at") or (user.get("account_mode") == "player" and user["role"] != "admin"):
        raise HTTPException(403, "需要有效的创作者账号")
    return user


def project(db, uid, project_id, lock=False):
    creator(db, uid)
    row = db.execute("select * from authoring_projects where id=%s and owner_id=%s" +
                     (" for update" if lock else ""), (uuid.UUID(str(project_id)), uid)).fetchone()
    if not row:
        raise HTTPException(404, "创作项目不存在")
    return row


def create_project(uid, project_key, title):
    if not re.fullmatch(r"[\w.-]{1,100}", project_key) or not 1 <= len(title.strip()) <= 180:
        raise HTTPException(400, "项目 key 或标题无效")
    with connect() as db:
        creator(db, uid)
        row = db.execute("""insert into authoring_projects(id,owner_id,project_key,title) values(%s,%s,%s,%s)
          on conflict(owner_id,project_key) do update set project_key=excluded.project_key returning *""",
                         (uuid.uuid4(), uid, project_key, title.strip())).fetchone()
    return expose(row)


def begin_upload(uid, project_id, size, sha256):
    if type(size) is not int or not 0 < size <= 50 * 1024 * 1024 or not re.fullmatch("[a-f0-9]{64}", sha256):
        raise HTTPException(400, "大小或 SHA256 无效")
    with connect() as db:
        db.execute("select id from users where id=%s for update", (uid,)).fetchone()
        project(db, uid, project_id, True)
        db.execute("delete from authoring_uploads where created_at<now()-interval '24 hours' and id not in "
                   "(select (input->>'upload_id')::uuid from authoring_jobs where kind='import' and status in ('pending','running'))")
        used = db.execute("select count(*) as n from authoring_uploads u join authoring_projects p on p.id=u.project_id "
                          "where p.owner_id=%s", (uid,)).fetchone()["n"]
        if used >= 4:
            raise HTTPException(429, "最多保留四个上传，请等待过期清理")
        row = db.execute("insert into authoring_uploads(id,project_id,size,sha256) values(%s,%s,%s,%s) returning id",
                         (uuid.uuid4(), project_id, size, sha256)).fetchone()
    return dict(upload_id=str(row["id"]), chunk_bytes=CHUNK_BYTES,
                http_url=f"/api/authoring/uploads/{row['id']}/content")


def upload(db, uid, upload_id):
    creator(db, uid)
    row = db.execute("select u.* from authoring_uploads u join authoring_projects p on p.id=u.project_id "
                     "where u.id=%s and p.owner_id=%s and u.created_at>now()-interval '24 hours' for update of u",
                     (uuid.UUID(str(upload_id)), uid)).fetchone()
    if not row:
        raise HTTPException(404, "上传引用不存在或已过期")
    return row


def upload_chunk(uid, upload_id, part, data):
    try:
        if len(data) > (CHUNK_BYTES + 2) // 3 * 4:
            raise ValueError()
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        raise HTTPException(400, "无效或过大的 Base64 分片") from None
    if type(part) is not int or not 0 <= part < 400 or not 0 < len(raw) <= CHUNK_BYTES:
        raise HTTPException(400, "分片编号或大小无效")
    with connect() as db:
        row = upload(db, uid, upload_id)
        old = db.execute("select data from authoring_upload_parts where upload_id=%s and part=%s", (upload_id, part)).fetchone()
        if old:
            if bytes(old["data"]) != raw:
                raise HTTPException(409, "分片已存在且内容不同")
        elif row["data"] is not None:
            raise HTTPException(409, "上传已完成")
        else:
            if row["received"] + len(raw) > row["size"]:
                raise HTTPException(413, "超过声明的上传大小")
            db.execute("insert into authoring_upload_parts values(%s,%s,%s)", (upload_id, part, raw))
            db.execute("update authoring_uploads set received=received+%s where id=%s", (len(raw), upload_id))
    return dict(upload_id=str(upload_id), part=part, accepted=True)


def complete_upload(uid, upload_id):
    with connect() as db:
        row = upload(db, uid, upload_id)
        if row["data"] is not None:
            return dict(upload_id=str(upload_id), complete=True)
        parts = db.execute("select part,data from authoring_upload_parts where upload_id=%s order by part", (upload_id,)).fetchall()
        if [p["part"] for p in parts] != list(range(len(parts))):
            raise HTTPException(409, "分片编号不连续")
        raw = b"".join(bytes(p["data"]) for p in parts)
        if len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise HTTPException(409, "上传大小或指纹不符")
        db.execute("update authoring_uploads set data=%s where id=%s", (raw, upload_id))
        db.execute("delete from authoring_upload_parts where upload_id=%s", (upload_id,))
    return dict(upload_id=str(upload_id), complete=True)


def package(uid, upload_id):
    with connect() as db:
        row = upload(db, uid, upload_id)
        if row["data"] is None:
            raise HTTPException(409, "文件尚未上传完成")
        return row, bytes(row["data"])


def validate_package(uid, upload_id):
    _, data = package(uid, upload_id)
    return inspect_package(data)[0]


def import_draft(uid, project_id, upload_id, expected_version, credential=None):
    uploaded, data = package(uid, upload_id)
    if str(uploaded["project_id"]) != str(project_id):
        raise HTTPException(404, "上传不属于该项目")
    report, _, _, _ = inspect_package(data)
    if not report["valid"]:
        return dict(accepted=False, report=report)
    with connect() as db:
        current = project(db, uid, project_id, True)
        previous = db.execute("select job_id from authoring_revisions where project_id=%s and fingerprint=%s",
                              (project_id, report["fingerprint"])).fetchone()
        if previous:
            return dict(job_id=str(previous["job_id"]), reused=True)
        active = db.execute("select * from authoring_jobs where project_id=%s and kind='import' and status in ('pending','running')",
                            (project_id,)).fetchone()
        if active:
            if active["input"]["fingerprint"] == report["fingerprint"]:
                return dict(job_id=str(active["id"]), reused=True)
            raise HTTPException(409, "该项目正在导入其他修订")
        if current["version"] != expected_version:
            raise HTTPException(409, "草稿版本冲突，请重新获取项目")
        jid = uuid.uuid4()
        db.execute("insert into authoring_jobs(id,project_id,owner_id,kind,input) values(%s,%s,%s,'import',%s)",
                   (jid, project_id, uid, Jsonb(dict(upload_id=str(upload_id), expected_version=expected_version,
                                                   fingerprint=report["fingerprint"], credential=credential))))
    EXECUTOR.submit(run_import, str(jid))
    return dict(job_id=str(jid), reused=False)


def _ensure_chunks(db, sid):
    from platform_app.knowledge._sync import _ensure_book
    script = db.execute("select * from scripts where id=%s", (sid,)).fetchone()
    book = _ensure_book(db, script)
    for chapter in db.execute("select * from script_chapters where script_id=%s order by chapter_index", (sid,)).fetchall():
        if db.execute("select 1 from document_chunks where script_id=%s and chapter_id=%s limit 1", (sid, chapter["id"])).fetchone():
            continue
        doc = db.execute("""insert into documents(book_id,script_id,chapter_id,source_kind,source_ref,title,content)
          values(%s,%s,%s,'chapter',%s,%s,%s) returning id""",
                         (book["id"], sid, chapter["id"], str(chapter["chapter_index"]), chapter["title"], chapter["content"])).fetchone()
        text = chapter["content"]
        for index, start in enumerate(range(0, len(text), 1200)):
            db.execute("""insert into document_chunks(book_id,script_id,chapter_id,document_id,chapter_index,chunk_index,content,token_count)
              values(%s,%s,%s,%s,%s,%s,%s,%s)""", (book["id"], sid, chapter["id"], doc["id"], chapter["chapter_index"], index,
                                             text[start:start+1200], len(text[start:start+1200])))


def run_import(job_id):
    try:
        with connect() as db:
            claimed = db.execute("select pg_try_advisory_xact_lock(hashtextextended(%s,0)) as owned", (job_id,)).fetchone()
            if not claimed["owned"]:
                return
            job = db.execute("select * from authoring_jobs where id=%s", (job_id,)).fetchone()
            if not job or job["status"] not in ("pending", "running"):
                return
            # The advisory lock survives until content and the success record commit.
            # Progress updates use another connection without exposing partial content.
            with connect() as status_db:
                status_db.execute("update authoring_jobs set status='running',progress=1,heartbeat_at=now() where id=%s", (job_id,))
            current = project(db, job["owner_id"], job["project_id"], True)
            from .oauth import check_credential
            check_credential(db, job["owner_id"], job["input"].get("credential"), "authoring:write")
            if current["version"] != job["input"]["expected_version"]:
                raise ValueError("草稿版本冲突")
            uploaded = db.execute("select data from authoring_uploads where id=%s and project_id=%s",
                                  (job["input"]["upload_id"], job["project_id"])).fetchone()
            report, contract, parsed, files = inspect_package(bytes(uploaded["data"]))
            if not report["valid"]:
                raise ValueError("内容校验失败")
            from platform_app.knowledge.script_pack import import_script_pack
            def progress(done, total):
                with connect() as status_db:
                    status_db.execute("update authoring_jobs set progress=%s,heartbeat_at=now() where id=%s and status='running'",
                                      (min(95, max(1, int(done/max(total, 1)*95))), job_id))
            imported = import_script_pack(bytes(uploaded["data"]), job["owner_id"], progress_cb=progress, db=db)
            if imported["warnings"]:
                raise ValueError("导入存在缺项：" + "; ".join(imported["warnings"])[:300])
            sid = imported["script_id"]
            _ensure_chunks(db, sid)
            check_credential(db, job["owner_id"], job["input"].get("credential"), "authoring:write")
            play = contract.play.model_dump()
            play["cover"] = ""
            if contract.media:
                from .media import store_cover
                play["cover"] = store_cover(job["owner_id"], files[contract.media[0].path])
            body = contract.model_dump()
            body["play"]["cover"] = play["cover"]
            revision = db.execute("""insert into authoring_revisions(project_id,version,fingerprint,script_id,contract,report,job_id)
              values(%s,%s,%s,%s,%s,%s,%s) returning id,version,script_id""",
              (job["project_id"], current["version"]+1, report["fingerprint"], sid, Jsonb(body), Jsonb(report), job_id)).fetchone()
            db.execute("update scripts set authoring_locked=true,is_public=false where id=%s", (sid,))
            db.execute("update authoring_projects set version=version+1 where id=%s", (job["project_id"],))
            db.execute("update authoring_jobs set status='succeeded',result=%s,progress=100,heartbeat_at=now() where id=%s",
                       (Jsonb(dict(revision)), job_id))
    except Exception as exc:
        log.exception("Authoring import failed: %s", job_id)
        with connect() as db:
            db.execute("update authoring_jobs set status='failed',error=%s,heartbeat_at=now() where id=%s",
                       (str(exc.detail if isinstance(exc, HTTPException) else exc)[:500], job_id))


def get_job(uid, job_id):
    with connect() as db:
        creator(db, uid)
        row = db.execute("select id,kind,status,result,error,progress,created_at from authoring_jobs where id=%s and owner_id=%s",
                         (uuid.UUID(str(job_id)), uid)).fetchone()
    if not row:
        raise HTTPException(404, "任务不存在")
    return expose(row)


def get_draft(uid, project_id, version=None):
    with connect() as db:
        row = project(db, uid, project_id)
        revisions = db.execute("select id,version,script_id,fingerprint,report,reviewed_at,contract,rights_note,"
                               "exists(select 1 from authoring_jobs j where j.project_id=r.project_id and j.kind='preview' "
                               "and j.status='succeeded' and j.input->>'revision_id'=r.id::text) as played from authoring_revisions r "
                               "where project_id=%s and (%s::int is null or version=%s) order by version desc limit 20",
                               (project_id, version, version)).fetchall()
        if version is not None and not revisions:
            raise HTTPException(404, "版本不存在")
        jobs = db.execute("select id,kind,status,error from authoring_jobs where project_id=%s order by created_at desc limit 20", (project_id,)).fetchall()
        playtests = db.execute("select id,status,result,error,input->>'revision_id' as revision_id from authoring_jobs "
                              "where project_id=%s and kind='preview' order by created_at desc limit 30", (project_id,)).fetchall()
        submissions = db.execute("select s.* from authoring_submissions s join authoring_revisions r on r.id=s.revision_id where r.project_id=%s order by s.created_at desc limit 50",
                                 (project_id,)).fetchall()
    for item in revisions:
        item["playtests"] = [expose(p) for p in playtests if p["revision_id"] == str(item["id"])]
        item["report"]["checks"]["playtest"] = "passed" if item.pop("played") else "not_run"
    return dict(project=expose(row), revisions=[expose(r) for r in revisions], jobs=[expose(j) for j in jobs],
                submissions=[expose(s) for s in submissions], url=f"/play/authoring?project={project_id}")


def revision(db, uid, revision_id):
    creator(db, uid)
    row = db.execute("select r.* from authoring_revisions r join authoring_projects p on p.id=r.project_id "
                     "where r.id=%s and p.owner_id=%s", (revision_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, "作品版本不存在")
    return row


def review(uid, revision_id, rights_note):
    if not 1 <= len(rights_note.strip()) <= 2000:
        raise HTTPException(400, "请提供来源与授权说明")
    with connect() as db:
        row = revision(db, uid, revision_id)
        db.execute("update authoring_revisions set reviewed_at=now(),rights_note=%s where id=%s", (rights_note.strip(), revision_id))
        db.execute("update scripts set review_status='reviewed',reviewed_at=now() where id=%s", (row["script_id"],))
    return dict(reviewed=True)


def submit(uid, revision_id):
    with connect() as db:
        row = revision(db, uid, revision_id)
        project(db, uid, row["project_id"], True)
        if not row["reviewed_at"] or not row["rights_note"]:
            raise HTTPException(409, "请先在项目页面复核此版本并填写来源授权说明")
        existing = db.execute("select * from authoring_submissions where revision_id=%s and status in ('pending_review','published')", (revision_id,)).fetchone()
        if existing:
            return expose(existing)
        row = db.execute("insert into authoring_submissions(id,revision_id) values(%s,%s) returning *", (uuid.uuid4(), revision_id)).fetchone()
    return expose(row)


def recover():
    if not federation.provider_enabled():
        return
    with connect() as db:
        jobs = db.execute("select id from authoring_jobs where kind='import' and status in ('pending','running')").fetchall()
    for job in jobs:
        EXECUTOR.submit(run_import, str(job["id"]))

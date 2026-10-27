"""Production budget applies across PostgreSQL connections and survives retries."""
# ruff: noqa: F811 -- pytest fixtures are imported by name.
import base64
import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from platform_app.authoring import budget, service
from platform_app.db import connect
from tests.integration.test_authoring import creator, isolated_database, upload  # noqa: F401


def test_import_queue_is_bounded_and_retryable(monkeypatch):
    service.start_executor()
    monkeypatch.setattr(service, "MAX_SCHEDULED_IMPORTS", 2)
    release = threading.Event()
    started = threading.Event()
    completed = []
    def work(job_id):
        started.set()
        assert release.wait(10)
        completed.append(job_id)
    monkeypatch.setattr(service, "run_import", work)
    ids = [str(uuid.uuid4()) for _ in range(3)]
    try:
        assert service._schedule_import(ids[0])
        assert started.wait(5)
        assert service._schedule_import(ids[1])
        assert not service._schedule_import(ids[2])
        release.set()
        for _ in range(200):
            with service._scheduled_lock:
                remaining = len(service._scheduled_imports)
            if remaining == 0:
                break
            time.sleep(.01)
        assert remaining == 0
        assert service._schedule_import(ids[2])
        for _ in range(200):
            if ids[2] in completed:
                break
            time.sleep(.01)
        assert set(completed) == set(ids)
    finally:
        release.set()


def test_recovery_scans_oldest_jobs_in_bounded_batches(creator, monkeypatch):
    from psycopg.types.json import Jsonb

    monkeypatch.setattr(service, "MAX_SCHEDULED_IMPORTS", 2)
    scheduled = []
    monkeypatch.setattr(service, "_schedule_import", scheduled.append)
    ids = []
    with connect() as db:
        for index in range(3):
            project = service.create_project(creator["uid"], uuid.uuid4().hex, "恢复队列")
            jid = uuid.uuid4()
            ids.append(jid)
            db.execute("insert into authoring_jobs(id,project_id,owner_id,kind,input,created_at) "
                       "values(%s,%s,%s,'import',%s, '1900-01-01'::timestamptz + %s * interval '1 second')",
                       (jid, project["id"], creator["uid"], Jsonb({}), index))
    try:
        service.recover()
        assert scheduled == ids[:2]
        with connect() as db:
            db.execute("update authoring_jobs set status='succeeded' where id=any(%s)", (ids[:2],))
        scheduled.clear()
        service.recover()
        assert ids[2] in scheduled
    finally:
        with connect() as db:
            db.execute("delete from authoring_jobs where id=any(%s)", (ids,))


def test_busy_budget_rejects_validation_before_reading_upload(creator, monkeypatch):
    def fail_if_read(*args):
        raise AssertionError("busy validation loaded package bytes")
    monkeypatch.setattr(service, "package", fail_if_read)
    with connect() as holder:
        budget.acquire(holder)
        with pytest.raises(HTTPException) as exc:
            service.validate_package(creator["uid"], "unused")
        assert exc.value.status_code == 429


def test_busy_budget_keeps_import_pending_until_recovery(creator, monkeypatch):
    project, upload_id = upload(creator)
    monkeypatch.setattr(service, "_schedule_import", lambda *_: False)
    task = service.import_draft(creator["uid"], project["id"], upload_id, 0)
    with connect() as holder:
        budget.acquire(holder)
        with ThreadPoolExecutor(1) as pool:
            pool.submit(service.run_import, task["job_id"]).result(timeout=10)
        assert service.get_job(creator["uid"], task["job_id"])["status"] == "pending"
    service.run_import(task["job_id"])
    assert service.get_job(creator["uid"], task["job_id"])["status"] == "succeeded"


def test_concurrent_upload_completion_rejects_busy_and_can_retry(creator, monkeypatch):
    from platform_app.authoring.examples import package_bytes

    raw = package_bytes()
    references = []
    for _ in range(2):
        project = service.create_project(creator["uid"], uuid.uuid4().hex, "原创项目")
        ref = service.begin_upload(creator["uid"], project["id"], len(raw), hashlib.sha256(raw).hexdigest())
        service.upload_chunk(creator["uid"], ref["upload_id"], 0, base64.b64encode(raw).decode())
        references.append(ref["upload_id"])

    started, release = threading.Event(), threading.Event()
    original_hash = hashlib.sha256

    def held_hash(data=b"", **kwargs):
        if data == raw and not started.is_set():
            started.set()
            assert release.wait(10)
        return original_hash(data, **kwargs)

    monkeypatch.setattr(service.hashlib, "sha256", held_hash)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.complete_upload, creator["uid"], references[0])
        assert started.wait(10)
        try:
            second = pool.submit(service.complete_upload, creator["uid"], references[1])
            with pytest.raises(HTTPException) as busy:
                second.result(timeout=10)
            assert busy.value.status_code == 429
        finally:
            release.set()
        assert first.result(timeout=10)["complete"]
    assert service.complete_upload(creator["uid"], references[1])["complete"]
    with connect() as db:
        row = service.upload(db, creator["uid"], references[0])
        assert row["complete"] and "data" not in row


def test_transmigrator_uses_existing_soul_origin_rules(creator):
    import uuid

    from platform_app.authoring import preview
    from platform_app.authoring.examples import example_files
    from platform_app.player.catalog import player_save
    from tests.integration.test_authoring_regressions import configured

    files = example_files()
    files["authoring.json"]["play"]["player_origin"] = "transmigrator"
    _, revision, _ = configured(creator, files)
    created = preview.create(creator["uid"], revision["id"], "visitor", str(uuid.uuid4()))
    save = player_save(creator["uid"], created["save_id"])
    assert save["state_snapshot"]["player"]["player_origin"] == "soul"

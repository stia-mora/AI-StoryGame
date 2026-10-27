import pytest

from platform_app.player.generation_progress import public_stage


@pytest.mark.parametrize("name,data,phase", [
    ("agent", {"phase": "llm_curator", "status": "running"}, "understanding"),
    ("agent", {"phase": "llm_curator", "status": "done"}, "retrieving"),
    ("agent", {"phase": "provider:private-worldbook"}, "retrieving"),
    ("agent", {"phase": "main_gm"}, "generating"),
    ("stage", {"phase": "retrieving"}, "retrieving"),
    ("stage", {"phase": "generating"}, "generating"),
    ("stage", {"phase": "done"}, "saving"),
    ("stage", {"phase": "saving"}, "saving"),
])
def test_progress_exposes_only_safe_phase_and_fixed_label(name, data, phase):
    result = public_stage(name, {**data, "prompt": "SECRET", "message": "SECRET", "plan": {"hidden": "SECRET"}})
    assert set(result) == {"phase", "label"}
    assert result["phase"] == phase
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("name,data", [
    ("agent", {"phase": "unknown", "message": "private"}),
    ("status", {"phase": "generating", "prompt": "private"}),
    ("stage", {"phase": "unknown"}),
])
def test_unknown_events_are_not_forwarded(name, data):
    assert public_stage(name, data) is None


def test_public_catalog_shares_only_explicit_opening_text():
    from platform_app.player.catalog import public_story

    story = {"id": 1, "title": "雾港", "introduction": "公开简介", "cover": "", "identities": [],
             "defaults": {"opening_preview": "  你打开了那封信。  ", "prompt": "PRIVATE", "birthpoint": "PRIVATE"}}
    public = public_story(story)
    assert public["opening_preview"] == "你打开了那封信。"
    assert "PRIVATE" not in str(public)
    story["defaults"]["opening_preview"] = {"text": "not a public string"}
    assert "opening_preview" not in public_story(story)
    story["defaults"] = {}
    assert "opening_preview" not in public_story(story)


def test_player_stream_forwards_sanitized_progress_through_the_actual_adapter(monkeypatch):
    import asyncio
    import uuid

    from starlette.responses import StreamingResponse

    import app
    from platform_app import branches
    from platform_app.api import player as api
    from platform_app.player.meter import current
    from routes.game import opening

    rid = uuid.uuid4()
    monkeypatch.setattr(api.catalog, "player_save", lambda *args: {"id": 9, "state_snapshot": {}})
    monkeypatch.setattr(api.catalog, "for_save", lambda *args: {})
    monkeypatch.setattr(api.catalog, "view", lambda *args: {"status": {}, "journey": []})
    monkeypatch.setattr(api.wallet, "reserve", lambda *args, **kwargs: ({
        "id": rid, "user_id": 3, "save_id": 9, "kind": "opening", "profile": {}, "rates": {}, "cap_micro": 1000000,
    }, False))
    monkeypatch.setattr(api.wallet, "heartbeat", lambda *args: True)
    monkeypatch.setattr(api.wallet, "release", lambda *args: None)
    monkeypatch.setattr(branches, "activate_save", lambda *args: None)
    monkeypatch.setattr(app, "_invalidate_user_cache", lambda *args: None)

    async def generate(api_user):
        async def chunks():
            yield api.event("agent", {"phase": "llm_curator", "message": "PRIVATE", "prompt": "PRIVATE"})
            yield api.event("stage", {"phase": "generating", "prompt": "PRIVATE"})
            yield api.event("token", {"text": "公开开场。"})
            yield api.event("stage", {"phase": "done"})
            current().receipt = {"text": "公开开场。", "saved": True}
        return StreamingResponse(chunks())

    monkeypatch.setattr(opening, "api_opening", generate)

    async def collect():
        response = await api.execute(api.Execute(save_id=9, kind="opening", quote_id=uuid.uuid4(), request_id=rid, action_id="test"), {"id": 3})
        return "".join([frame async for frame in response.body_iterator])

    stream = asyncio.run(collect())
    assert "PRIVATE" not in stream
    assert '"phase": "understanding"' in stream
    assert '"phase": "generating"' in stream
    assert '"phase": "saving"' in stream
    assert "公开开场。" in stream
    assert "event: receipt" in stream
    assert str(rid) not in api.RUNS


@pytest.mark.parametrize("run_uid,exposes_progress", [(3, True), (4, False)])
def test_status_progress_remains_scoped_to_the_authenticated_owner(monkeypatch, run_uid, exposes_progress):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from platform_app.api import player as api

    request_id = uuid4()
    req = {"status": "running", "created_at": "2026-10-27T12:00:00Z"}
    @contextmanager
    def connect():
        yield SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: req.copy()))

    monkeypatch.setattr(api, "connect", connect)
    monkeypatch.setattr(api.wallet, "reap", lambda *args: None)
    monkeypatch.setattr(api, "RUNS", {str(request_id): SimpleNamespace(uid=run_uid, progress={"phase": "retrieving", "label": "正在整理故事资料"})})
    result = api.request_status(request_id, {"id": 3})
    assert ("progress" in result) == exposes_progress

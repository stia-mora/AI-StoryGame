"""Public player API. No BYOK settings, source chapters, prompts or debug events."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date
from typing import Literal
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictBool, model_validator

from core.sse import SSE_HEADERS, with_keepalive
from platform_app.db import connect, expose
from platform_app.player import catalog, wallet
from platform_app.player.meter import Run, active_run

from ._deps import current_user, require_user

router = APIRouter(prefix="/api/player")
RUNS: dict[str, Run] = {}


def require_player(user=Depends(require_user)):
    from core.config import is_local_mode

    if not is_local_mode() and user.get("role") != "admin" and not user.get("email_verified"):
        raise HTTPException(403, "请先完成账户验证，再开始游玩")
    return user


class MartialSoulChoice(BaseModel):
    model_config = {"extra": "forbid"}
    mode: str = Field(pattern="^(recommended|custom|random)$")
    name: str = Field(default="", max_length=40)


class Create(BaseModel):
    story_id: int
    name: str = Field(min_length=1, max_length=40)
    identity_id: str = Field(default="", max_length=80)
    background: str = Field(default="", max_length=1200)
    custom_identity: str = Field(default="", max_length=80)
    martial_soul: MartialSoulChoice | None = None


class Quote(BaseModel):
    save_id: int
    kind: str = Field(pattern="^(opening|turn|guide)$")
    message: str = Field(default="", max_length=6000)
    reveal_future: StrictBool = False

    @model_validator(mode="after")
    def guide_disclosure(self):
        if self.reveal_future and self.kind != "guide":
            raise ValueError("未来资料许可仅用于游玩助手")
        return self


class Execute(Quote):
    quote_id: uuid.UUID
    request_id: uuid.UUID
    action_id: str = Field(min_length=1, max_length=100)


class Redeem(BaseModel):
    code: str = Field(min_length=1, max_length=120)


def estimate_usage(uid, save, profile, kind, message, *, reveal_future=False):
    """Forecast complete foreground calls; debug/retrieval caches are not repeated prompts."""
    if kind == "guide":
        from platform_app.player.guide import forecast

        return forecast(uid, save["id"], message, profile, reveal_future=reveal_future)
    with connect() as db:
        previous = db.execute(
            """select r.kind,sum(c.input_tokens) as input_tokens,
                      bool_or(c.phase='curator') as has_curator
               from player_requests r join player_llm_calls c on c.request_id=r.id and c.billable
               where r.user_id=%s and r.save_id=%s and r.status='settled'
                 and coalesce((r.receipt->>'partial')::boolean,false)=false
                 and r.profile->>'api_id'=%s and r.profile->>'model'=%s
               group by r.id order by r.created_at desc limit 5""",
            (uid, save["id"], profile["api_id"], profile["model"]),
        ).fetchall()
    sample = next(
        (r for r in previous if r["kind"] == kind and (kind == "opening" or r["has_curator"])), None
    )
    output = int(profile["max_output"])
    if kind == "turn":
        output += min(int(profile["max_output"]), 1800)  # Curator plus full GM narration/state output.
    if sample and sample["input_tokens"]:
        return int(sample["input_tokens"]) + len(message) + 2000, output
    opening = next((r for r in previous if r["kind"] == "opening" and r["input_tokens"]), None)
    if kind == "turn" and opening:
        # Curator sees a compact action/state packet, not the full main GM retrieval prompt.
        return int(opening["input_tokens"]) + len(message) + 6000, output
    state = save.get("state_snapshot") or {}
    relevant = {
        k: state[k]
        for k in ("player", "player_character", "world", "relationships", "history")
        if k in state
    }
    memory = state.get("memory") or {}
    relevant["memory"] = {
        k: memory[k]
        for k in ("current_objective", "main_quest", "abilities", "resources")
        if k in memory
    }
    context = len(json.dumps(relevant, ensure_ascii=False, default=str)) // 2 + len(message) + 8000
    return context + (6000 if kind == "turn" else 0), output


@router.get("/bootstrap")
def bootstrap(user=Depends(require_player)):
    uid = user["id"]
    stories = catalog.listed_stories()
    saves = catalog.list_saves(uid)
    return dict(
        user={
            "id": uid,
            "name": user.get("display_name") or user["username"],
            "creator": user.get("role") == "admin"
            or user.get("account_mode", "creator") == "creator",
            "admin": user.get("role") == "admin",
        },
        stories=[catalog.public_story(s) for s in stories],
        saves=saves["items"], save_total=saves["total"],
        wallet=wallet.wallet(uid),
    )


@router.get("/catalog")
def public_catalog():
    rows = catalog.listed_stories()
    return {"stories": [catalog.public_story(row) for row in rows]}


@router.get("/session")
def player_session(user=Depends(current_user)):
    # Anonymous discovery must never pass through the private bootstrap endpoint.
    return {"authenticated": bool(user)}


@router.get("/stories/{story_id}/cover")
def story_cover(story_id: int):
    selected = catalog.story(story_id, new=True)
    return _cover_response(selected)


@router.get("/saves/{sid}/cover")
def save_cover(sid: int, user=Depends(require_player)):
    save = catalog.player_save(user["id"], sid)
    selected = save.get("player_story_snapshot") or catalog.story(save["player_story_id"])
    return _cover_response(selected, private=True)


def _cover_response(selected, *, private=False):
    from platform_app.storage import resolve_path
    cover = selected.get("cover") or ""
    if not cover.startswith("/api/storage/"):
        raise HTTPException(404, "封面不存在")
    path = resolve_path(cover.removeprefix("/api/storage/"))
    if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}:
        raise HTTPException(404, "封面不存在")
    return FileResponse(path, headers={"Cache-Control": ("private" if private else "public")+",max-age=300"})


@router.post("/saves")
def create(body: Create, user=Depends(require_player)):
    with wallet.idle_account(user["id"]):
        return _create(body, user)


@router.get("/saves")
def list_saves(page: int = Query(default=1, ge=1, le=1000000),
               query: str = Query(default="", max_length=120), user=Depends(require_player)):
    return catalog.list_saves(user["id"], page=page, query=query)


def _create(body: Create, user, *, selected=None, preview_revision=None, preview_key=None):
    from platform_app import branches, workspace

    selected = selected or catalog.story(body.story_id, new=True)
    identity = next(
        (i for i in selected["identities"] if str(i.get("id")) == body.identity_id), None
    )
    if body.custom_identity.strip():
        identity = {"name": body.custom_identity.strip(), "player_origin": selected["defaults"].get("player_origin", "native")}
    if not identity:
        raise HTTPException(400, "请选择推荐身份")
    if not body.name.strip():
        raise HTTPException(400, "请填写角色名字")
    defaults = selected["defaults"]
    from platform_app.player.character_creation import prepare

    setup = prepare(defaults, body.martial_soul.model_dump() if body.martial_soul else None)
    story_snapshot = {k: selected[k] for k in ("id", "script_id", "profile_id", "title", "introduction", "cover", "identities", "defaults")}
    if preview_revision:
        story_snapshot["preview_creation"] = dict(identity_id=body.identity_id, name=body.name)
    name = str(identity.get("character_name") or body.name).strip()
    card = {
        "name": name,
        "role": identity.get("role") or identity.get("name") or "",
        "background": "\n".join(
            filter(None, [identity.get("background", ""), body.background.strip()])
        ),
    }
    if identity.get("subject"):
        with connect() as db:
            bound = db.execute("select * from character_cards where id=%s and script_id=%s and enabled",
                               (identity.get("card_id"), selected["script_id"])).fetchone()
        card = {**(bound or {}), **card, "authoring_subject": identity["subject"], "bound_npc_card_id": (bound or {}).get("id")}
    result = workspace.create_save(
        user["id"],
        selected["script_id"],
        f"{name}的故事",
        new_card=card,
        birthpoint=identity.get("birthpoint") or defaults.get("birthpoint"),
        story_intent=defaults.get("story_intent"),
        player_origin=identity.get("player_origin") or defaults.get("player_origin"),
        identity_known=defaults.get("identity_known"),
        player_story_id=selected["id"],
        player_setup=setup,
        player_story_snapshot=story_snapshot,
        authoring_revision_id=preview_revision,
        authoring_preview_key=preview_key,
    )
    sid = int((result.get("save") or result)["id"])
    branches.activate_save(user["id"], sid)
    import app

    app._invalidate_user_cache(user)
    return catalog.view(user["id"], sid)


@router.get("/saves/{sid}")
def view(sid: int, user=Depends(require_player)):
    return catalog.view(user["id"], sid)


@router.get("/saves/{sid}/history")
def history(sid: int, before: int = Query(gt=0), limit: int = Query(default=20, ge=1, le=50), user=Depends(require_player)):
    result = catalog.view(user["id"], sid, before=before, limit=limit)
    return {key: result[key] for key in ("messages", "history_before")}


@router.post("/quote")
def quote(body: Quote, user=Depends(require_player)):
    from core.request_limits import rate_allowed
    if not rate_allowed(f"player-quote:{user['id']}", 60):
        raise HTTPException(429, "报价过于频繁，请稍后重试", headers={"Retry-After": "60"})
    save = catalog.player_save(user["id"], body.save_id)
    selected = catalog.for_save(save)
    from platform_app.player.character_creation import pending

    if body.kind == "opening" and catalog.view(user["id"], body.save_id)["has_opening"]:
        raise HTTPException(409, "这个存档已有开场，请继续故事")
    if body.kind == "turn" and pending(save.get("state_snapshot") or {}):
        raise HTTPException(409, "请先生成开场完成觉醒，再继续行动")
    if body.kind in {"turn", "guide"} and not body.message.strip():
        raise HTTPException(400, "请填写行动或问题")
    # Disclosure only: settlement exclusively uses provider usage. Forecast both calls,
    # avoiding oversized holds caused by saved debug/context caches in state JSON.
    estimate, estimate_output = estimate_usage(
        user["id"], save, selected["profile"], body.kind, body.message,
        reveal_future=body.reveal_future,
    )
    tool_allowance = 4000 if selected["profile"].get("tools_mode") == "internal" else 0
    estimate += tool_allowance
    return wallet.make_quote(
        user["id"], save, selected["profile"], body.kind, body.message, estimate, estimate_output,
        reveal_future=body.reveal_future,
    )


def event(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/execute")
async def execute(body: Execute, user=Depends(require_player)):
    save = catalog.player_save(user["id"], body.save_id)
    catalog.for_save(save)
    from platform_app.player.character_creation import pending

    if body.kind == "turn" and pending(save.get("state_snapshot") or {}):
        raise HTTPException(409, "请先生成开场完成觉醒，再继续行动")
    req, replay = wallet.reserve(
        user["id"],
        save,
        str(body.quote_id),
        str(body.request_id),
        body.action_id,
        body.kind,
        body.message,
        reveal_future=body.reveal_future,
    )
    if replay:
        if req["status"] == "settled":

            async def replay_stream():
                yield event("receipt", req["receipt"])
                yield event("saved", {"saved": True})
                yield event("done", {})

            return StreamingResponse(replay_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
        raise HTTPException(409, "执行请求已受理，请查询请求状态")
    run = Run(req)
    if body.kind == "opening":
        from copy import deepcopy

        from platform_app.player.character_creation import pending

        run.character_setup = deepcopy(pending(save.get("state_snapshot") or {}))
    if body.kind != "guide":
        from platform_app.player import pacing

        try:
            run.pacing = pacing.context(catalog.view(run.uid, run.save_id), body.message)
        except Exception:
            wallet.release(run.uid, run.id, "未能读取回合基线")
            raise
    RUNS[run.id] = run

    async def pulse():
        while True:
            await asyncio.sleep(30)
            if not await asyncio.to_thread(wallet.heartbeat, run.uid, run.id):
                run.stop.set()
                return

    async def stream():
        from platform_app.player.experience import PlayerTextGuard

        visible_guard = PlayerTextGuard()
        token = active_run.set(run)
        ticker = None
        legacy = None
        text = ""
        try:
            if body.kind == "guide":
                from platform_app.player.guide import generate

                ticker = asyncio.create_task(pulse())
                yield event("saving", {"state": "thinking"})
                receipt = await asyncio.to_thread(generate, run, body.message)
                yield event("receipt", receipt)
                yield event("saved", {"saved": True})
                yield event("done", {})
                return
            import app
            from platform_app import branches

            # Wallet serialization prevents two tabs activating different saves during generation.
            await asyncio.to_thread(branches.activate_save, run.uid, run.save_id)
            app._invalidate_user_cache(user)
            wallet.heartbeat(run.uid, run.id)
            ticker = asyncio.create_task(pulse())
            yield event("saving", {"state": "generating"})
            if body.kind == "opening":
                from routes.game.opening import api_opening

                legacy = await api_opening(api_user=user)
            else:
                from routes.game.chat import api_chat
                from schemas.game import ChatRequest

                # This action answers the previous round's suggestions. Keep confirmations,
                # but do not let old GM options suppress extraction of the new four actions.
                state = app._ensure_loaded(user, ensure_gm=False)
                questions = state.data.setdefault("permissions", {}).get("pending_questions") or []
                state.data["permissions"]["pending_questions"] = [
                    q for q in questions if not str(q.get("source", "")).startswith("gm:")
                ]
                state.data["structured_options"] = []
                legacy = await api_chat(
                    ChatRequest(
                        message=body.message, save_id=run.save_id, action_id=body.action_id
                    ),
                    api_user=user,
                )
            buffer = ""
            async for raw in legacy.body_iterator:
                buffer += raw.decode() if isinstance(raw, bytes) else raw
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    name = "message"
                    data = {}
                    for line in frame.splitlines():
                        if line.startswith("event:"):
                            name = line[6:].strip()
                        if line.startswith("data:"):
                            data = json.loads(line[5:])
                    if name == "token":
                        visible = visible_guard.feed(data.get("text", ""))
                        text += visible
                        if visible:
                            yield event("token", {"text": visible})
                    elif name == "error":
                        yield event(
                            "error",
                            {
                                "message": "本轮暂未完成，请稍后重试。未保存的回合不会扣积分。",
                                "kind": data.get("kind", "service_error"),
                            },
                        )
            tail = visible_guard.flush()
            if tail:
                text += tail
                yield event("token", {"text": tail})
            if run.receipt:
                yield event("receipt", run.receipt)
                yield event("saved", {"saved": True})
            else:
                wallet.release(run.uid, run.id, "生成失败或未保存")
                yield event("saved", {"saved": False})
            yield event("done", {})
        except (asyncio.CancelledError, GeneratorExit):
            run.stop.set()
            if legacy:
                with suppress(BaseException):
                    await legacy.body_iterator.aclose()
            # Opening does not have the legacy chat cancellation persistence handler.
            if body.kind == "opening" and text.strip() and not run.receipt:
                with suppress(Exception):
                    import app
                    from platform_app import branches

                    state = app._ensure_loaded(user, ensure_gm=False)
                    state.data.setdefault("history", []).append(
                        {"role": "assistant", "content": text}
                    )
                    run.partial = True
                    run.committing = True
                    branches.record_runtime_turn("", text, user_id=run.uid, state_data=state.data)
            raise
        except Exception:
            logging.getLogger(__name__).exception("Managed player execution failed")
            yield event(
                "error",
                {
                    "message": "故事服务暂时不可用，请重试。未保存的回合不会扣积分。",
                    "kind": "service_error",
                },
            )
            yield event("done", {})
        finally:
            run.stop.set()
            if ticker:
                ticker.cancel()
                with suppress(asyncio.CancelledError):
                    await ticker
            if not run.receipt:
                wallet.release(run.uid, run.id, "回合未提交")
            RUNS.pop(run.id, None)
            active_run.reset(token)

    return StreamingResponse(
        with_keepalive(stream()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/requests/{request_id}")
def request_status(request_id: uuid.UUID, user=Depends(require_player)):
    wallet.reap(user["id"])
    with connect() as db:
        req = db.execute(
            "select status,receipt,reason from player_requests where id=%s and user_id=%s",
            (request_id, user["id"]),
        ).fetchone()
    if not req:
        raise HTTPException(404, "找不到此请求")
    return req


@router.post("/requests/{request_id}/stop")
async def stop(request_id: uuid.UUID, user=Depends(require_player)):
    request_status(request_id, user)
    with connect() as db:
        wallet.lock_wallet(db, user["id"])
        db.execute(
            "update player_requests set stop_requested=true where id=%s and user_id=%s and status in ('reserved','running')",
            (request_id, user["id"]),
        )
    run = RUNS.get(str(request_id))
    if run and run.uid == user["id"]:
        run.stop.set()
        if run.kind != "guide":
            from routes.game.chat import api_stop

            await api_stop(api_user=user)
    return {"ok": True}


@router.get("/saves/{sid}/guide")
def guide_history(sid: int, user=Depends(require_player)):
    from platform_app.player.guide import history

    return {"items": history(user["id"], sid)}


@router.get("/wallet")
def balance(user=Depends(require_player)):
    return wallet.wallet(user["id"])


@router.get("/ledger")
def ledger(
    page: int = Query(default=1, ge=1, le=100000),
    page_size: int = Query(default=10, ge=1, le=50),
    kind: Literal["", "daily", "expire", "reserve", "settle", "release", "redeem", "grant"] = "",
    q: str = Query(default="", max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
    before: int = Query(default=0, ge=0),
    user=Depends(require_player),
):
    from platform_app.player.ledger import history

    return history(user["id"], page=page, page_size=page_size, kind=kind, query=q,
                   date_from=date_from, date_to=date_to, before=before)


@router.get("/requests/{request_id}/usage")
def usage(request_id: uuid.UUID, user=Depends(require_player)):
    request_status(request_id, user)
    with connect() as db:
        rows = db.execute(
            "select phase,input_tokens,output_tokens,cached_tokens,reasoning_tokens,billable,reason from player_llm_calls where request_id=%s order by created_at,id",
            (request_id,),
        ).fetchall()
    return {"items": rows}


@router.post("/redeem")
def redeem(body: Redeem, user=Depends(require_player)):
    return wallet.redeem(user["id"], body.code)

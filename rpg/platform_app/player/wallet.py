"""Integer microcredit ledger. Every mutation locks wallet before request/save."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from decimal import Decimal

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from platform_app.db import connect

MICRO = 1_000_000
REAP_BATCH_SIZE = 128
DEFAULT_RATES = dict(
    version=1, input_micro_per_token=1000, output_micro_per_token=4000, daily_micro=100 * MICRO
)


def rates(db):
    row = db.execute("select value from app_config where key='player_rates'").fetchone()
    return {**DEFAULT_RATES, **((row or {}).get("value") or {})}


def ledger(db, uid, kind, free=0, permanent=0, held=0, request=None, reason="", *, preview=0, preview_held=0):
    db.execute(
        """insert into player_ledger(user_id,kind,free_delta,permanent_delta,held_delta,request_id,reason,preview_delta,preview_held_delta)
               values(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (uid, kind, free, permanent, held, request, reason, preview, preview_held),
    )


def lock_wallet(db, uid):
    db.execute("insert into player_wallets(user_id) values(%s) on conflict do nothing", (uid,))
    w = db.execute(
        "select *, (now() at time zone 'Asia/Shanghai')::date as today from player_wallets where user_id=%s for update",
        (uid,),
    ).fetchone()
    if w["free_day"] != w["today"]:
        allowance = int(rates(db)["daily_micro"])
        if w["free_micro"]:
            ledger(db, uid, "expire", -w["free_micro"], reason="昨日免费积分到期")
        ledger(db, uid, "daily", allowance, reason="每日免费积分")
        db.execute(
            "update player_wallets set free_day=%s,free_micro=%s where user_id=%s",
            (w["today"], allowance, uid),
        )
        w.update(free_day=w["today"], free_micro=allowance)
    return w


def public_wallet(w):
    return dict(
        free_micro=w["free_micro"],
        permanent_micro=w["permanent_micro"],
        held_micro=w["held_micro"],
        free_day=str(w["free_day"]),
        rates={"input": 1, "output": 4},
        micro_per_point=MICRO,
        preview_micro=w.get("preview_micro", 0),
        preview_held_micro=w.get("preview_held_micro", 0),
    )


def wallet(uid):
    reap(uid)
    with connect() as db:
        result = public_wallet(lock_wallet(db, uid))
        pricing = rates(db)
        result["rates"] = {
            "input": pricing["input_micro_per_token"] / 1000,
            "output": pricing["output_micro_per_token"] / 1000,
        }
        return result


@contextmanager
def idle_account(uid):
    """Serialize free save activation with the account's metered execution mutex."""
    reap(uid)
    with connect() as db:
        lock_wallet(db, uid)
        if db.execute(
            "select id from player_requests where user_id=%s and status in ('reserved','running')",
            (uid,),
        ).fetchone():
            raise HTTPException(409, "当前故事仍在生成，请等保存完成后再创建角色")
        yield


def cost(input_tokens, output_tokens, rate):
    return int(input_tokens) * int(rate["input_micro_per_token"]) + int(output_tokens) * int(
        rate["output_micro_per_token"]
    )


def fingerprint(kind, message, reveal_future=False):
    if reveal_future and kind != "guide":
        raise HTTPException(400, "未来资料许可仅用于游玩助手")
    suffix = "\0guide:future" if reveal_future else ""
    return hashlib.sha256((kind + "\0" + message + suffix).encode()).hexdigest()


def _preview_wallet(db, uid):
    from platform_app.authoring.service import creator
    creator(db, uid)
    w = lock_wallet(db, uid)
    if not w.get("preview_granted_at"):
        amount = 10_000 * MICRO
        db.execute("update player_wallets set preview_micro=preview_micro+%s,preview_granted_at=now() where user_id=%s", (amount, uid))
        ledger(db, uid, "creator_grant", reason="创作者一次性试玩额度", preview=amount)
        w["preview_micro"] += amount
    return w


def preview_wallet(uid):
    reap(uid)
    with connect() as db:
        return public_wallet(_preview_wallet(db, uid))


def _preview_save(db, uid, save):
    if not save.get("authoring_revision_id"):
        return False
    row = db.execute("select 1 from authoring_revisions r join authoring_projects p on p.id=r.project_id "
                     "join game_saves g on g.authoring_revision_id=r.id where g.id=%s and g.user_id=%s "
                     "and p.owner_id=%s and g.script_id=r.script_id", (save["id"], uid, uid)).fetchone()
    if not row:
        raise HTTPException(403, "试玩额度仅限自己的作品")
    return True


def make_quote(uid, save, profile, kind, message, estimate_tokens, estimate_output=None,
               *, reveal_future=False):
    profile = {
        key: profile[key]
        for key in (
            "id",
            "name",
            "credential_owner_id",
            "api_id",
            "model",
            "max_output",
            "enabled",
            "version",
            "script_id",
            "tools_mode",
        )
        if key in profile
    }
    if kind == "guide":
        profile["guide_options"] = {"reveal_future": reveal_future is True}
    with connect() as db:
        preview = _preview_save(db, uid, save)
        w = _preview_wallet(db, uid) if preview else lock_wallet(db, uid)
        r = rates(db)
        estimate = cost(
            estimate_tokens,
            min(int(profile["max_output"]), 1200) if estimate_output is None else estimate_output,
            r,
        )
        cap = max(5 * MICRO, estimate * 2)
        qid = str(uuid.uuid4())
        db.execute(
            """insert into player_quotes(id,user_id,save_id,kind,message_hash,base_commit,profile,rates,estimate_micro,cap_micro,funding)
                   values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                qid,
                uid,
                save["id"],
                kind,
                fingerprint(kind, message, reveal_future),
                save.get("active_commit_id"),
                Jsonb(profile),
                Jsonb(r),
                estimate,
                cap,
                "preview" if preview else "player",
            ),
        )
        return dict(
            id=qid,
            estimate_micro=estimate,
            cap_micro=cap,
            affordable=(w["preview_micro"] if preview else w["free_micro"] + w["permanent_micro"]) >= cap,
            funding="preview" if preview else "player",
            wallet=public_wallet(w),
            rate_version=r["version"],
        )


def reserve(uid, save, quote_id, request_id, action_id, kind, message, *, reveal_future=False):
    # Reject malformed identifiers before SQL; replay can never access another account.
    try:
        request_id, quote_id = str(uuid.UUID(request_id)), str(uuid.UUID(quote_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "请求标识无效") from None
    reap(uid)
    with connect() as db:
        w = lock_wallet(db, uid)
        old = db.execute(
            "select * from player_requests where id=%s for update", (request_id,)
        ).fetchone()
        if old:
            if (
                old["user_id"] != uid
                or old["save_id"] != save["id"]
                or old["action_id"] != action_id
                or old["quote_id"] != uuid.UUID(quote_id)
            ):
                raise HTTPException(409, "请求标识已用于其他行动")
            prior_quote = db.execute(
                "select message_hash from player_quotes where id=%s", (old["quote_id"],)
            ).fetchone()
            if (
                old["kind"] != kind
                or not prior_quote
                or prior_quote["message_hash"] != fingerprint(kind, message, reveal_future)
            ):
                raise HTTPException(409, "请求标识已用于其他行动")
            return old, True
        q = db.execute(
            "select *, expires_at>now() as valid from player_quotes where id=%s and user_id=%s",
            (quote_id, uid),
        ).fetchone()
        if (
            not q
            or not q["valid"]
            or q["save_id"] != save["id"]
            or q["message_hash"] != fingerprint(kind, message, reveal_future)
        ):
            raise HTTPException(409, "报价已失效，请重新确认")
        fresh = db.execute(
            "select active_commit_id from game_saves where id=%s", (save["id"],)
        ).fetchone()
        if q["base_commit"] != fresh.get("active_commit_id"):
            raise HTTPException(409, "存档已更新，请刷新后重新报价")
        if db.execute(
            "select id from player_requests where user_id=%s and status in ('reserved','running')",
            (uid,),
        ).fetchone():
            raise HTTPException(409, "还有一轮正在进行，请等待或停止")
        cap = q["cap_micro"]
        if q.get("funding") == "preview":
            if not _preview_save(db, uid, save):
                raise HTTPException(403, "试玩报价不能用于普通游玩")
            w = _preview_wallet(db, uid)
            if w["preview_micro"] < cap:
                raise HTTPException(402, "试玩积分不足，请兑换试玩码")
            db.execute("update player_wallets set preview_micro=preview_micro-%s,preview_held_micro=preview_held_micro+%s where user_id=%s", (cap, cap, uid))
            req = db.execute("""insert into player_requests(id,user_id,save_id,quote_id,action_id,kind,free_day,
              free_hold,permanent_hold,cap_micro,rates,profile,funding,preview_hold)
              values(%s,%s,%s,%s,%s,%s,%s,0,0,%s,%s,%s,'preview',%s) returning *""",
              (request_id, uid, save["id"], quote_id, action_id, kind, w["free_day"], cap, Jsonb(q["rates"]), Jsonb(q["profile"]), cap)).fetchone()
            ledger(db, uid, "reserve", request=request_id, reason="试玩预留", preview=-cap, preview_held=cap)
            return req, False
        if _preview_save(db, uid, save):
            raise HTTPException(403, "试玩存档必须使用专用报价")
        if w["free_micro"] + w["permanent_micro"] < cap:
            raise HTTPException(402, "积分不足以预留本轮封顶费用")
        free = min(w["free_micro"], cap)
        permanent = cap - free
        db.execute(
            "update player_wallets set free_micro=free_micro-%s,permanent_micro=permanent_micro-%s,held_micro=held_micro+%s where user_id=%s",
            (free, permanent, cap, uid),
        )
        req = db.execute(
            """insert into player_requests(id,user_id,save_id,quote_id,action_id,kind,free_day,free_hold,permanent_hold,cap_micro,rates,profile)
                          values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
            (
                request_id,
                uid,
                save["id"],
                quote_id,
                action_id,
                kind,
                w["free_day"],
                free,
                permanent,
                cap,
                Jsonb(q["rates"]),
                Jsonb(q["profile"]),
            ),
        ).fetchone()
        ledger(db, uid, "reserve", -free, -permanent, cap, request_id, "回合预留")
        return req, False


def lock_request(db, uid, request_id, save_id=None):
    w = lock_wallet(db, uid)
    req = db.execute(
        "select *,expires_at>now() as valid from player_requests where id=%s and user_id=%s for update",
        (request_id, uid),
    ).fetchone()
    if (
        not req
        or req["status"] not in ("reserved", "running")
        or not req["valid"]
        or (save_id and req["save_id"] != save_id)
    ):
        raise HTTPException(409, "回合已结束或租约过期，不能继续保存")
    return w, req


def settle(db, uid, request_id, commit_id, text, options, partial=False):
    w, req = lock_request(db, uid, request_id)
    if not str(text).strip():
        raise ValueError("空回复不能结算")
    calls = db.execute(
        "select * from player_llm_calls where request_id=%s order by created_at,id", (request_id,)
    ).fetchall()
    charged_calls = [c for c in calls if c["billable"]]
    inp = sum(c["input_tokens"] for c in charged_calls)
    out = sum(c["output_tokens"] for c in charged_calls)
    actual = cost(inp, out, req["rates"])
    charged = min(actual, req["cap_micro"])
    free_used = min(req["free_hold"], charged)
    is_preview = req.get("funding") == "preview"
    permanent_used = 0 if is_preview else charged - free_used
    free_back = req["free_hold"] - free_used if w["free_day"] == req["free_day"] else 0
    permanent_back = req["permanent_hold"] - permanent_used
    if is_preview:
        db.execute("update player_wallets set preview_micro=preview_micro+%s,preview_held_micro=preview_held_micro-%s where user_id=%s",
                   (req["preview_hold"]-charged, req["preview_hold"], uid))
    else:
        db.execute(
            "update player_wallets set free_micro=free_micro+%s,permanent_micro=permanent_micro+%s,held_micro=held_micro-%s where user_id=%s",
            (free_back, permanent_back, req["cap_micro"], uid),
        )
    receipt = dict(
        request_id=str(req["id"]),
        charged_micro=charged,
        actual_micro=actual,
        platform_micro=actual - charged,
        input_tokens=inp,
        output_tokens=out,
        rate_version=req["rates"]["version"],
        partial=partial,
        text=text,
        options=options or [],
        saved=True,
        funding=req.get("funding", "player"),
    )
    db.execute(
        "update player_requests set status='settled',actual_micro=%s,charged_micro=%s,receipt=%s,commit_id=%s where id=%s",
        (actual, charged, Jsonb(receipt), commit_id, request_id),
    )
    ledger(
        db,
        uid,
        "settle",
        free_back,
        permanent_back,
        0 if is_preview else -req["cap_micro"],
        request_id,
        "已保存回复，实扣 " + str(Decimal(charged) / MICRO),
        preview=req["preview_hold"]-charged if is_preview else 0,
        preview_held=-req["preview_hold"] if is_preview else 0,
    )
    return receipt


def release(uid, request_id, reason="回合未保存", expired_only=False):
    with connect() as db:
        w = lock_wallet(db, uid)
        req = db.execute(
            "select *,expires_at<=now() as expired from player_requests where id=%s and user_id=%s for update",
            (request_id, uid),
        ).fetchone()
        if not req or req["status"] not in ("reserved", "running"):
            return
        if expired_only and not req["expired"]:
            return
        if req.get("funding") == "preview":
            amount = req["preview_hold"]
            db.execute("update player_wallets set preview_micro=preview_micro+%s,preview_held_micro=preview_held_micro-%s where user_id=%s", (amount, amount, uid))
            db.execute("update player_requests set status='released',reason=%s where id=%s", (reason, request_id))
            ledger(db, uid, "release", request=request_id, reason=reason, preview=amount, preview_held=-amount)
            return
        free = req["free_hold"] if w["free_day"] == req["free_day"] else 0
        db.execute(
            "update player_wallets set free_micro=free_micro+%s,permanent_micro=permanent_micro+%s,held_micro=held_micro-%s where user_id=%s",
            (free, req["permanent_hold"], req["cap_micro"], uid),
        )
        db.execute(
            "update player_requests set status='released',reason=%s where id=%s",
            (reason, request_id),
        )
        ledger(
            db, uid, "release", free, req["permanent_hold"], -req["cap_micro"], request_id, reason
        )


def heartbeat(uid, request_id):
    with connect() as db:
        row = db.execute(
            """update player_requests set status='running',heartbeat_at=now(),expires_at=now()+interval '5 minutes'
                           where id=%s and user_id=%s and status in ('reserved','running') and expires_at>now() returning stop_requested""",
            (request_id, uid),
        ).fetchone()
        return bool(row and not row["stop_requested"])


def reap(uid=None):
    with connect() as db:
        # Preserve quotes referenced by requests/receipts. Batch and skip locked rows
        # so cleanup never competes with a reservation transaction for long.
        db.execute("""delete from player_quotes where id in (
            select q.id from player_quotes q where q.expires_at<now()-interval '1 hour'
            and not exists(select 1 from player_requests r where r.quote_id=q.id)
            order by q.expires_at limit 1000 for update of q skip locked)""")
        rows = db.execute(
            "select id,user_id from player_requests where status in ('reserved','running') and expires_at<=now()"
            + (" and user_id=%s" if uid is not None else "")
            + " order by expires_at,id limit %s",
            (uid, REAP_BATCH_SIZE) if uid is not None else (REAP_BATCH_SIZE,),
        ).fetchall()
    for row in rows:
        release(row["user_id"], str(row["id"]), "租约过期，未提交预留已释放", expired_only=True)


def redeem(uid, code):
    digest = hashlib.sha256(code.strip().upper().encode()).hexdigest()
    with connect() as db:
        balance = lock_wallet(db, uid)
        row = db.execute(
            "select *, (expires_at is null or expires_at>now()) as valid from player_codes where code_hash=%s for update",
            (digest,),
        ).fetchone()
        if (
            not row
            or not row["valid"]
            or not row["enabled"]
            or row["used_count"] >= row["max_uses"]
        ):
            raise HTTPException(400, "兑换码无效、已到期或已领完")
        if db.execute(
            "select 1 from player_redemptions where code_id=%s and user_id=%s", (row["id"], uid)
        ).fetchone():
            raise HTTPException(409, "你已经兑换过此码")
        if row.get("purpose") == "preview":
            _preview_wallet(db, uid)
        elif balance["free_micro"] + balance["permanent_micro"] + balance["held_micro"] > 5000 * MICRO:
            raise HTTPException(409, "当前游玩积分（含预留）已超过 5000，请先使用已有积分后再兑换。")
        db.execute(
            "insert into player_redemptions(code_id,user_id) values(%s,%s)", (row["id"], uid)
        )
        db.execute("update player_codes set used_count=used_count+1 where id=%s", (row["id"],))
        if row.get("purpose") == "preview":
            db.execute("update player_wallets set preview_micro=preview_micro+%s where user_id=%s", (row["amount_micro"], uid))
            ledger(db, uid, "redeem", preview=row["amount_micro"], reason=row["label"])
        else:
            db.execute(
                "update player_wallets set permanent_micro=permanent_micro+%s where user_id=%s",
                (row["amount_micro"], uid),
            )
            ledger(db, uid, "redeem", permanent=row["amount_micro"], reason=row["label"])
    return wallet(uid)

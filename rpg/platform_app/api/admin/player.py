"""Administrator controls for the player service; credentials remain private."""

import hashlib
import secrets
from decimal import Decimal, InvalidOperation

from fastapi import Depends, HTTPException, Request
from psycopg.types.json import Jsonb

from platform_app.db import connect, expose
from platform_app.perms import script_owned
from platform_app.player.wallet import MICRO, ledger, lock_wallet, rates

from ._shared import _require_admin, _set_app_config, _write_audit, router


def points(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > 1_000_000:
            raise ValueError()
        micro = amount * MICRO
        if micro != micro.to_integral_value():
            raise ValueError()
        return int(micro)
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(400, "积分必须大于零，最多六位小数") from None


@router.get("/api/admin/player")
def settings(admin=Depends(_require_admin)):
    from model_registry import load_catalog_for_user

    with connect() as db:
        result = {
            key: [expose(r) for r in db.execute(sql).fetchall()]
            for key, sql in {
                "profiles": "select * from player_model_profiles order by id",
                "stories": "select * from player_stories order by sort_order,id",
                "codes": "select id,label,amount_micro,expires_at,max_uses,used_count,enabled,purpose from player_codes order by id desc limit 100",
                "bills": "select id,user_id,save_id,status,charged_micro,actual_micro,reason,created_at,funding from player_requests order by created_at desc limit 100",
                "accounts": "select id,username,display_name,account_mode,role from users order by id desc limit 200",
            }.items()
        }
        result["rates"] = rates(db)
        result["scripts"] = [
            expose(r)
            for r in db.execute(
                "select id,title,review_status from scripts where owner_id=%s order by id desc",
                (admin["id"],),
            ).fetchall()
        ]
        result["credentials"] = [
            dict(r)
            for r in db.execute(
                "select api_id from user_api_credentials where user_id=%s and enabled",
                (admin["id"],),
            ).fetchall()
        ]
    result["models"] = load_catalog_for_user(admin["id"])
    return result


@router.post("/api/admin/player/profiles")
async def profile(request: Request, admin=Depends(_require_admin)):
    body = await request.json()
    from core.llm_backend import supports_text_model
    from platform_app.user_credentials import resolve_api_key, resolved_is_usable

    api = str(body.get("api_id") or "")
    model = str(body.get("model") or "")
    if not supports_text_model(admin["id"], api, model):
        raise HTTPException(400, "请选择已有文本模型")
    if api == "vertex_ai":
        from core.vertex_sa import load_sa_credentials

        credential, _ = load_sa_credentials(admin["id"])
        if not credential:
            raise HTTPException(400, "服务凭据不可用")
    elif not resolved_is_usable(resolve_api_key(admin["id"], api)):
        raise HTTPException(400, "服务凭据不可用")
    maximum = int(body.get("max_output", 6144))
    tools_mode = body.get("tools_mode", "internal")
    if tools_mode not in ("internal", "none"):
        raise HTTPException(400, "工具模式无效")
    if not 256 <= maximum <= 8192:
        raise HTTPException(400, "输出预算须在 256–8192 Token")
    with connect() as db:
        args = (
            str(body.get("name", "玩家模型"))[:80],
            admin["id"],
            api,
            model,
            maximum,
            bool(body.get("enabled", True)),
        )
        if body.get("id"):
            row = db.execute(
                "update player_model_profiles set name=%s,credential_owner_id=%s,api_id=%s,model=%s,max_output=%s,enabled=%s,version=version+1,updated_at=now() where id=%s returning *",
                (*args, int(body["id"])),
            ).fetchone()
        else:
            row = db.execute(
                "insert into player_model_profiles(name,credential_owner_id,api_id,model,max_output,enabled) values(%s,%s,%s,%s,%s,%s) returning *",
                args,
            ).fetchone()
        if not row:
            raise HTTPException(404, "服务模型不存在")
        db.execute(
            "update player_model_profiles set tools_mode=%s where id=%s", (tools_mode, row["id"])
        )
        row["tools_mode"] = tools_mode
        _write_audit(
            db, admin, "player.profile", "profile", str(row["id"]), {"api_id": api, "model": model}
        )
    return expose(row)


@router.post("/api/admin/player/stories")
async def story(request: Request, admin=Depends(_require_admin)):
    body = await request.json()
    status = body.get("status", "unlisted")
    if status not in ("published", "unlisted", "suspended"):
        raise HTTPException(400, "上架状态无效")
    identities = body.get("identities") or []
    defaults = body.get("defaults") or {}
    from platform_app.player.character_creation import config as creation_config

    if not isinstance(defaults, dict):
        raise HTTPException(400, "开局配置必须是对象")
    creation_config(defaults)
    if (
        not isinstance(identities, list)
        or not identities
        or any(not isinstance(i, dict) or not i.get("id") or not i.get("name") for i in identities)
    ):
        raise HTTPException(400, "请至少配置一个有 id 和 name 的推荐身份")
    if len({str(i["id"]) for i in identities}) != len(identities):
        raise HTTPException(400, "身份 id 不能重复")
    if any('character_name' in i and (not isinstance(i['character_name'], str)
           or not 1 <= len(i['character_name'].strip()) <= 40) for i in identities):
        raise HTTPException(400, "原著角色姓名须为1至40字")
    cover = str(body.get("cover") or "")
    if cover and not cover.startswith(("/assets/", "https://")):
        raise HTTPException(400, "封面请使用 HTTPS 或本地 assets 地址")
    with connect() as db:
        script = script_owned(db, int(body["script_id"]), admin["id"])
        if not script:
            raise HTTPException(403, "只能上架你有编辑权的剧本")
        if status == "published":
            from platform_app.workspace.listing import _readiness_for_scripts

            readiness = _readiness_for_scripts(db, [script["id"]])[script["id"]]
            if (
                script.get("review_status", "unreviewed") != "reviewed"
                or "chunks" in readiness["missing"]
                or "canon" in readiness["missing"]
            ):
                raise HTTPException(409, "上架前请完成导入、章节准备和剧本复核")
        if not db.execute(
            "select id from player_model_profiles where id=%s and enabled",
            (int(body["profile_id"]),),
        ).fetchone():
            raise HTTPException(400, "服务模型不可用")
        row = db.execute(
            """insert into player_stories(script_id,profile_id,title,introduction,cover,identities,defaults,status,sort_order)
          values(%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(script_id) do update set
          profile_id=excluded.profile_id,title=excluded.title,introduction=excluded.introduction,cover=excluded.cover,
          identities=excluded.identities,defaults=excluded.defaults,status=excluded.status,sort_order=excluded.sort_order,updated_at=now() returning *""",
            (
                script["id"],
                int(body["profile_id"]),
                str(body.get("title") or script["title"])[:180],
                str(body.get("introduction") or "")[:1200],
                cover,
                Jsonb(identities),
                Jsonb(defaults),
                status,
                int(body.get("sort_order") or 0),
            ),
        ).fetchone()
        _write_audit(db, admin, "player.story", "story", str(row["id"]), {"status": status})
    return expose(row)


@router.post("/api/admin/player/rates")
async def update_rates(request: Request, admin=Depends(_require_admin)):
    body = await request.json()
    input_micro = points(body.get("input_per_1000"))
    output_micro = points(body.get("output_per_1000"))
    daily = points(body.get("daily_points"))
    if input_micro % 1000 or output_micro % 1000:
        raise HTTPException(400, "每千 Token 费率须为 0.001 积分的整数倍")
    inp = input_micro // 1000
    out = output_micro // 1000
    with connect() as db:
        db.execute("select pg_advisory_xact_lock(761031)")
        updated = dict(
            version=int(rates(db)["version"]) + 1,
            input_micro_per_token=inp,
            output_micro_per_token=out,
            daily_micro=daily,
        )
        _set_app_config(db, "player_rates", updated)
        _write_audit(db, admin, "player.rates", details=updated)
    return updated


@router.post("/api/admin/player/grants")
async def grant(request: Request, admin=Depends(_require_admin)):
    body = await request.json()
    amount = points(body.get("points"))
    reason = str(body.get("reason") or "").strip()
    uid = int(body["user_id"])
    if not reason:
        raise HTTPException(400, "发放积分必须填写原因")
    with connect() as db:
        if not db.execute("select id from users where id=%s", (uid,)).fetchone():
            raise HTTPException(404, "账户不存在")
        lock_wallet(db, uid)
        db.execute(
            "update player_wallets set permanent_micro=permanent_micro+%s where user_id=%s",
            (amount, uid),
        )
        ledger(db, uid, "grant", permanent=amount, reason=reason)
        _write_audit(
            db, admin, "player.grant", "user", str(uid), {"micro": amount, "reason": reason}
        )
    return {"ok": True}


@router.post("/api/admin/player/codes")
async def code(request: Request, admin=Depends(_require_admin)):
    body = await request.json()
    with connect() as db:
        if body.get("id"):
            db.execute(
                "update player_codes set enabled=%s where id=%s",
                (bool(body.get("enabled")), int(body["id"])),
            )
            _write_audit(db, admin, "player.code_disable", "code", str(body["id"]))
            return {"ok": True}
        plain = secrets.token_hex(12).upper()
        amount = points(body.get("points"))
        maximum = int(body.get("max_uses", 1))
        purpose = body.get("purpose", "player")
        if purpose not in ("player", "preview"):
            raise HTTPException(400, "兑换码用途无效")
        if not 1 <= maximum <= 1_000_000:
            raise HTTPException(400, "兑换人数上限无效")
        row = db.execute(
            "insert into player_codes(code_hash,label,amount_micro,expires_at,max_uses,purpose) values(%s,%s,%s,%s,%s,%s) returning id",
            (
                hashlib.sha256(plain.encode()).hexdigest(),
                str(body.get("label") or "积分兑换")[:120],
                amount,
                body.get("expires_at") or None,
                maximum,
                purpose,
            ),
        ).fetchone()
        _write_audit(
            db,
            admin,
            "player.code_create",
            "code",
            str(row["id"]),
            {"micro": amount, "max_uses": maximum},
        )
    return {"id": row["id"], "code": plain, "message": "码值仅此次展示，请妥善保存"}

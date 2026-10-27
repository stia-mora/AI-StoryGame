"""First-party PKCE authorization server and common creator authentication."""
from __future__ import annotations

import base64
import hashlib
import html
import re
import secrets
import uuid
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from psycopg.types.json import Jsonb

from platform_app import auth, federation
from platform_app.db import connect

from .contract import SCOPES
from .service import creator

router = APIRouter()


def resource():
    return federation.official_base() + "/mcp/authoring"


def enabled():
    if not federation.provider_enabled():
        raise HTTPException(404, "创作服务未开启")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _limited(request, name, maximum=30):
    key = f"authoring-oauth:{name}:{request.client.host if request.client else 'unknown'}"
    if not federation.rate_ok(key, maximum, 60):
        raise HTTPException(429, "请求过于频繁", headers={"Retry-After": "60"})


def session_user(request):
    enabled()
    user = auth.user_from_token(request.cookies.get("rpg_session"))
    if not user:
        raise HTTPException(401, "请先登录")
    with connect() as db:
        creator(db, user["id"])
    return user


def check_credential(db, uid, credential, scope):
    enabled()
    creator(db, uid)
    if credential is None:
        return  # The caller used a verified browser session.
    kind, token_hash = credential["kind"], credential["hash"]
    if kind == "pat":
        row = db.execute("select scopes from personal_access_tokens where user_id=%s and token_hash=%s "
                         "and revoked_at is null and expires_at>now()", (uid, token_hash)).fetchone()
    else:
        row = db.execute("select scopes from authoring_oauth_grants where user_id=%s and access_hash=%s "
                         "and revoked_at is null and access_expires>now() and resource=%s", (uid, token_hash, resource())).fetchone()
    if not row or scope not in row["scopes"]:
        raise HTTPException(403, "授权已失效或缺少权限")


def verify_bearer(token, scope=None):
    enabled()
    credential = dict(kind="pat" if token.startswith(federation.PAT_PREFIX) else "oauth", hash="")
    if credential["kind"] == "pat":
        try:
            result = federation.verify_pat(token, required_scope=scope)
        except PermissionError:
            raise HTTPException(401, "令牌无效或权限不足") from None
        credential["hash"] = federation._hash(token)
        result["credential"] = credential
        return result
    credential["hash"] = digest(token)
    with connect() as db:
        row = db.execute("select user_id,scopes,access_expires from authoring_oauth_grants where access_hash=%s "
                         "and revoked_at is null and access_expires>now() and resource=%s", (digest(token), resource())).fetchone()
        if not row:
            raise HTTPException(401, "令牌已失效")
        user = creator(db, row["user_id"])
    if scope and scope not in row["scopes"]:
        raise HTTPException(403, "缺少权限 " + scope)
    return dict(user=dict(user), scopes=row["scopes"], credential=credential,
                expires_at=int(row["access_expires"].timestamp()))


def request_user(request, scope="authoring:read"):
    enabled()
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        result = verify_bearer(header[7:], scope)
        return {**result["user"], "_credential": result["credential"]}
    return session_user(request)


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp/authoring")
def protected_metadata():
    enabled()
    return dict(resource=resource(), authorization_servers=[federation.official_base()], scopes_supported=SCOPES,
                bearer_methods_supported=["header"])


@router.get("/.well-known/oauth-authorization-server")
def server_metadata():
    enabled()
    base = federation.official_base()
    return dict(issuer=base, authorization_endpoint=base+"/oauth/authoring/authorize",
                token_endpoint=base+"/oauth/authoring/token", registration_endpoint=base+"/oauth/authoring/register",
                revocation_endpoint=base+"/oauth/authoring/revoke", response_types_supported=["code"],
                grant_types_supported=["authorization_code", "refresh_token"],
                token_endpoint_auth_methods_supported=["none"], code_challenge_methods_supported=["S256"],
                scopes_supported=SCOPES, authorization_response_iss_parameter_supported=True)


def valid_redirect(uri):
    try:
        parsed = urlsplit(uri)
        return (len(uri) <= 1000 and not parsed.fragment and not parsed.username and not parsed.password
                and bool(parsed.hostname) and (parsed.scheme == "https" or
                    parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")))
    except ValueError:
        return False


async def body(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise HTTPException(413, "授权请求过大")
    request._body = bytes(raw)
    if request.headers.get("content-type", "").startswith("application/json"):
        return await request.json()
    return dict(await request.form())


@router.post("/oauth/authoring/register")
async def register(request: Request):
    enabled()
    _limited(request, "register", 10)
    data = await body(request)
    redirects = data.get("redirect_uris", [])
    if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 10 or
            any(not isinstance(uri, str) or not valid_redirect(uri) for uri in redirects)
            or data.get("token_endpoint_auth_method", "none") != "none"):
        return JSONResponse(dict(error="invalid_client_metadata"), 400)
    cid = "authoring_" + secrets.token_urlsafe(24)
    with connect() as db:
        db.execute("insert into authoring_oauth_clients(id,name,redirect_uris) values(%s,%s,%s)",
                   (cid, str(data.get("client_name") or "MCP Client")[:120], Jsonb(redirects)))
    return JSONResponse(dict(client_id=cid, client_name=str(data.get("client_name") or "MCP Client")[:120],
                             redirect_uris=redirects, token_endpoint_auth_method="none",
                             grant_types=["authorization_code", "refresh_token"], response_types=["code"]), 201)


@router.get("/oauth/authoring/authorize")
def authorize(request: Request):
    enabled()
    _limited(request, "authorize")
    data = dict(request.query_params)
    with connect() as db:
        client = db.execute("select * from authoring_oauth_clients where id=%s", (data.get("client_id", ""),)).fetchone()
        if not client or data.get("redirect_uri") not in client["redirect_uris"]:
            raise HTTPException(400, "客户端或回调地址无效")
        scopes = data.get("scope", "authoring:read").split()
        if (data.get("response_type") != "code" or data.get("code_challenge_method") != "S256"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data.get("code_challenge", ""))
                or not scopes or not set(scopes) <= set(SCOPES)
                or data.get("resource") != resource() or len(data.get("state", "")) > 2000):
            raise HTTPException(400, "授权范围、资源或 PKCE 参数无效")
        user = auth.user_from_token(request.cookies.get("rpg_session"))
        if not user:
            return RedirectResponse("/play/login?" + urlencode(dict(next=str(request.url.path)+"?"+request.url.query)), 303)
        creator(db, user["id"])
        rid, csrf = uuid.uuid4(), secrets.token_urlsafe(32)
        data.update(scopes=scopes, uid=user["id"], csrf=digest(csrf))
        db.execute("insert into authoring_oauth_requests(id,client_id,data) values(%s,%s,%s)", (rid, client["id"], Jsonb(data)))
    labels = "".join("<li>" + html.escape(s) + "</li>" for s in scopes)
    page = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            "<title>授权创作助手</title><body><main style='max-width:42rem;margin:10vh auto;font:16px system-ui;padding:24px'>"
            f"<h1>授权 {html.escape(client['name'])}</h1><p>账号：{html.escape(user['username'])}</p><ul>{labels}</ul>"
            "<p>允许助手访问你的创作项目。试玩仅使用自己的专用试玩余额；上架仍需平台审批。</p>"
            f"<form method='post'><input type='hidden' name='request_id' value='{rid}'>"
            f"<input type='hidden' name='csrf' value='{csrf}'>"
            "<button name='decision' value='allow'>授权</button> <button name='decision' value='deny'>拒绝</button>"
            "</form></main></body></html>")
    return HTMLResponse(page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/oauth/authoring/authorize")
async def consent(request: Request):
    user = session_user(request)
    fields = await body(request)
    with connect() as db:
        row = db.execute("delete from authoring_oauth_requests where id=%s and expires_at>now() returning *", (uuid.UUID(fields.get("request_id", "")),)).fetchone()
        if not row or row["data"]["uid"] != user["id"] or not secrets.compare_digest(row["data"]["csrf"], digest(fields.get("csrf", ""))):
            raise HTTPException(403, "授权请求已失效")
        data = row["data"]
        result = dict(state=data.get("state", ""), iss=federation.official_base())
        if fields.get("decision") == "allow":
            code = secrets.token_urlsafe(32)
            db.execute("""insert into authoring_oauth_grants(id,user_id,client_id,scopes,redirect_uri,challenge,resource,code_hash)
              values(%s,%s,%s,%s,%s,%s,%s,%s)""", (uuid.uuid4(), user["id"], row["client_id"], Jsonb(data["scopes"]),
                                                     data["redirect_uri"], data["code_challenge"], resource(), digest(code)))
            result["code"] = code
        else:
            result["error"] = "access_denied"
    redirect = data["redirect_uri"] + ("&" if "?" in data["redirect_uri"] else "?") + urlencode(result)
    return RedirectResponse(redirect, 303)


@router.post("/oauth/authoring/token")
async def exchange(request: Request):
    enabled()
    _limited(request, "token", 60)
    data = await body(request)
    grant = None
    with connect() as db:
        if data.get("grant_type") == "authorization_code":
            grant = db.execute("select * from authoring_oauth_grants where code_hash=%s and code_expires>now() "
                               "and revoked_at is null for update", (digest(data.get("code", "")),)).fetchone()
            verifier = data.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            if (not grant or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) or
                    not secrets.compare_digest(grant["challenge"], challenge) or
                    data.get("redirect_uri") != grant["redirect_uri"]):
                grant = None
        elif data.get("grant_type") == "refresh_token":
            token_hash = digest(data.get("refresh_token", ""))
            grant = db.execute("select * from authoring_oauth_grants where refresh_hash=%s and refresh_expires>now() "
                               "and revoked_at is null for update", (token_hash,)).fetchone()
            if not grant:
                db.execute("update authoring_oauth_grants set revoked_at=now() where id in "
                           "(select grant_id from authoring_oauth_refresh_history where token_hash=%s)", (token_hash,))
        if not grant or data.get("client_id") != grant["client_id"] or data.get("resource") != grant["resource"]:
            return JSONResponse(dict(error="invalid_grant"), 400)
        creator(db, grant["user_id"])
        if data.get("grant_type") == "refresh_token":
            db.execute("insert into authoring_oauth_refresh_history values(%s,%s)", (token_hash, grant["id"]))
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        db.execute("update authoring_oauth_grants set code_hash=null,access_hash=%s,access_expires=now()+interval '1 hour',"
                   "refresh_hash=%s,refresh_expires=now()+interval '30 days' where id=%s",
                   (digest(access), digest(refresh), grant["id"]))
    return JSONResponse(dict(access_token=access, token_type="Bearer", expires_in=3600,
                             refresh_token=refresh, scope=" ".join(grant["scopes"])),
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/authoring/revoke")
async def revoke(request: Request):
    enabled()
    data = await body(request)
    hashed = digest(data.get("token", ""))
    with connect() as db:
        db.execute("update authoring_oauth_grants set revoked_at=now() where client_id=%s "
                   "and (access_hash=%s or refresh_hash=%s)", (data.get("client_id", ""), hashed, hashed))
    return JSONResponse({}, headers={"Cache-Control": "no-store"})

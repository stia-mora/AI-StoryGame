"""platform_app/api/storage_routes.py — 统一文件服务路由（S1）。

GET /api/storage/{kind}/{filename}
  · kind 白名单：ai_images / avatars / scripts / library
  · 扩展名白名单：png / jpg / jpeg / webp（scripts 额外允许 txt / md）
  · 穿越防护：经 storage.resolve_path 校验
  · 返回 FileResponse

旧路由 /api/images/file/* 由 api/images.py 保留（W1-B 改）。
旧路由 /api/profile/avatar/file/* 由 frontend_routes.py 保留（老 URL 不破）。
"""
from __future__ import annotations

import os
import re
from contextlib import nullcontext

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..db import connect
from ..storage import resolve_path
from ._deps import require_user

router = APIRouter()

# ---------------------------------------------------------------------------
# 白名单配置
# ---------------------------------------------------------------------------

_KIND_ALLOWLIST = frozenset({"ai_images", "avatars", "scripts", "library"})

_EXT_ALLOWLIST = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_EXT_ALLOWLIST_SCRIPTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".txt", ".md"})


def require_storage_access(user_id: int, kind: str, filename: str, *, db=None) -> None:
    """Authorize both current and legacy URLs against the file's actual owner.

    Public references must belong to that owner: merely placing someone else's
    URL in a public card or profile must not make their private file public.
    """
    key = f"{kind}/{filename}"
    # Migration 72 derived avatar owners from an editable URL. Only accept the
    # uploader ID encoded in the server-generated avatar filename.
    avatar_match = re.fullmatch(r"u([1-9][0-9]*)_[0-9]+\.(?:png|jpg|jpeg|webp)", filename)
    avatar_owner = int(avatar_match.group(1)) if kind == "avatars" and avatar_match else None
    urls = [f"/api/storage/{key}"]
    if kind == "ai_images":
        urls.append(f"/api/images/file/{filename}")
    elif kind == "avatars":
        urls.append(f"/api/profile/avatar/file/{filename}")
    with connect() if db is None else nullcontext(db) as connection:
        allowed = connection.execute("""
            with owners as (
              select user_id from user_assets where storage_key = %s
                and (%s <> 'avatars' or user_id = %s)
                and (kind <> 'script_txt' or (split_part(replace(storage_key, chr(92), '/'), '/', 1) = 'scripts'
                     and split_part(replace(storage_key, chr(92), '/'), '/', 2) = 'user_' || user_id::text))
              union
              select user_id from ai_images where url = any(%s)
            )
            select 1 from owners o where o.user_id = %s
              or exists (select 1 from users u where u.id=o.user_id and u.avatar_url=any(%s))
              or exists (
                select 1 from scripts s where s.owner_id=o.user_id and s.cover_image_url=any(%s)
                  and (s.is_public or exists (select 1 from user_script_subscriptions us
                                               where us.script_id=s.id and us.user_id=%s))
              )
              or exists (
                select 1 from character_cards c left join scripts s on s.id=c.script_id
                where c.avatar_path=any(%s) and (
                  (c.user_id=o.user_id and c.card_type='pc' and c.is_public) or
                  (s.owner_id=o.user_id and (s.is_public or exists (
                    select 1 from user_script_subscriptions us where us.script_id=s.id and us.user_id=%s)))
                )
              )
              or exists (
                select 1 from card_persona_images i join character_cards c on c.id=i.card_id
                where i.image_url=any(%s) and c.user_id=o.user_id and c.card_type='pc' and c.is_public
              ) limit 1
        """, (key, kind, avatar_owner, urls, user_id, urls, urls, user_id, urls, user_id, urls)).fetchone()
    if not allowed:
        raise HTTPException(status_code=404, detail="文件不存在")


# ---------------------------------------------------------------------------
# 服务端点
# ---------------------------------------------------------------------------

@router.get("/api/storage/{kind}/{filename}")
async def serve_storage_file(kind: str, filename: str, request: Request) -> FileResponse:
    """统一文件服务：白名单 kind + 扩展名 + 穿越防护 → FileResponse。

    仅允许所有者和已公开或已订阅内容所引用的图片。
    """
    user = require_user(request)
    # kind 白名单
    if kind not in _KIND_ALLOWLIST:
        raise HTTPException(status_code=404, detail="未知 kind")

    # 扩展名白名单（按 kind 选取）
    ext = os.path.splitext(filename)[-1].lower()
    allowed_exts = _EXT_ALLOWLIST_SCRIPTS if kind == "scripts" else _EXT_ALLOWLIST
    if ext not in allowed_exts:
        raise HTTPException(status_code=404, detail="不支持的文件类型")

    # 穿越防护（resolve_path 内部校验）
    storage_key = f"{kind}/{filename}"
    require_storage_access(user["id"], kind, filename)
    try:
        path = resolve_path(storage_key)
    except ValueError:
        raise HTTPException(status_code=404, detail="路径非法") from None

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)

    return FileResponse(str(path))

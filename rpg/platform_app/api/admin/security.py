"""Admin editor for the same validated policy used by authentication."""
from __future__ import annotations

from fastapi import Depends, Request
from ...security_policy import KEY, SecurityPolicy, read

from ...db import connect
from .._deps import _client_ip, json_response
from ._shared import _require_admin, _set_app_config, _write_audit, router



@router.get("/api/admin/security-config")
async def admin_get_security_config(admin=Depends(_require_admin)):
    with connect() as db:
        cfg = read(db)
    return json_response(cfg)


@router.post("/api/admin/security-config")
async def admin_set_security_config(
    request: Request,
    admin=Depends(_require_admin),
):
    body = await request.json()
    ip = _client_ip(request)

    with connect() as db:
        update = SecurityPolicy(**{**read(db), **body}).model_dump()
        _set_app_config(db, KEY, update)
        _write_audit(db, admin, "config.security", details=update, ip=ip)

    return json_response({"ok": True})

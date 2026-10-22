"""One-time email authentication limited to cancelling a pending account deletion."""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from . import auth
from .db import connect, init_db
from .security import generate_email_code, hash_email_code, normalize_email, verify_email_code


def request_code(email, ip=""):
    email = normalize_email(email)
    if not email or "@" not in email:
        raise ValueError("请填写有效的邮箱地址")
    try:
        auth._check_rate_limit(ip, email)
    except auth.RateLimited as exc:
        raise HTTPException(429, "验证尝试过于频繁", headers={"Retry-After": str(exc.retry_after_sec)}) from exc
    if auth._ip_budget_exceeded("recovery:ip", ip, 5, 600):
        return {"ok": True}
    init_db()
    code = generate_email_code(6)
    with connect() as db:
        user = db.execute(
            "select u.id from users u join account_delete_queue q on q.user_id=u.id "
            "where lower(u.email)=%s and u.email_verified and u.deactivated_at is not null "
            "and coalesce(u.ban_reason,'')='' and q.completed_at is null "
            "and q.scheduled_hard_delete_at>now()", (email,),
        ).fetchone()
        if not user:
            return {"ok": True}
        db.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (email,))
        recent = db.execute(
            "select 1 from email_verifications where email=%s and purpose='account_recovery' "
            "and created_at>now()-interval '60 seconds'", (email,),
        ).fetchone()
        if recent:
            return {"ok": True}
        db.execute("update email_verifications set used_at=now() where email=%s and purpose='account_recovery' and used_at is null", (email,))
        db.execute(
            "insert into email_verifications(email,code_hash,purpose,expires_at,ip,ua) values(%s,%s,'account_recovery',%s,%s,'')",
            (email, hash_email_code(code), datetime.now(UTC)+timedelta(minutes=10), ip),
        )
    from .email import send_recovery_code_email
    from .email import EmailSendError
    try:
        send_recovery_code_email(email, code)
    except EmailSendError:
        auth._log.warning("account recovery mail could not be delivered")
    return {"ok": True}


def confirm(email, code, ip=""):
    email = normalize_email(email)
    try:
        auth._check_rate_limit(ip, email)
    except auth.RateLimited as exc:
        raise HTTPException(429, "验证尝试过于频繁", headers={"Retry-After": str(exc.retry_after_sec)}) from exc
    if auth._verify_locked(email):
        raise ValueError("验证尝试次数过多，请稍后重试")
    with connect() as db:
        db.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (email,))
        row = db.execute(
            "select * from email_verifications where email=%s and purpose='account_recovery' "
            "and used_at is null and expires_at>now() order by created_at desc,id desc limit 1 for update", (email,),
        ).fetchone()
        if not row or not verify_email_code(code, row["code_hash"]):
            auth._record_verify_fail(email)
            raise ValueError("验证码错误或已过期")
        user = db.execute("select * from users where lower(email)=%s and email_verified for update", (email,)).fetchone()
        queue = db.execute(
            "select user_id from account_delete_queue where user_id=%s and completed_at is null "
            "and scheduled_hard_delete_at>now() for update", ((user or {}).get("id"),),
        ).fetchone()
        if not user or not queue or user.get("ban_reason"):
            raise ValueError("没有可以撤销的删除申请")
        auth._assert_email_not_banned(db, email)
        db.execute("delete from account_delete_queue where user_id=%s", (user["id"],))
        user = db.execute("update users set deactivated_at=null,updated_at=now() where id=%s returning *", (user["id"],)).fetchone()
        db.execute("update email_verifications set used_at=now() where id=%s", (row["id"],))
        token = auth._issue_session(db, user["id"])
    auth._clear_verify_fail(email)
    return dict(user), token

"""platform_app.dmca — DMCA strike 计数与账户终止辅助逻辑。

依赖表（由 v37 迁移创建）:
  dmca_strikes       — 每条 strike 记录
  banned_users       — 永久封禁名单（email + ip）
  account_delete_queue — 待终止队列
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# 累犯阈值：达到此次数自动触发账户终止流程
DMCA_STRIKE_THRESHOLD = 3


def increment_strike(db, user_id: int, reason: str) -> dict:
    """为指定用户添加一条 DMCA strike 记录。

    返回:
        dict with keys:
          - strike_count (int): 该用户当前累计 strike 数
          - terminate (bool): 是否已达到终止阈值
          - strike_id (int): 新写入的 strike 记录 ID
    """
    row = db.execute(
        "insert into dmca_strikes(user_id,strike_count,last_strike_at,last_strike_reason) "
        "values(%s,1,now(),%s) on conflict(user_id) do update set "
        "strike_count=dmca_strikes.strike_count+1,last_strike_at=now(),last_strike_reason=excluded.last_strike_reason "
        "returning user_id,strike_count", (user_id, reason),
    ).fetchone()
    strike_id = row["user_id"]
    strike_count = row["strike_count"]

    terminate = strike_count >= DMCA_STRIKE_THRESHOLD

    log.info(
        "dmca.strike user_id=%d count=%d/%d terminate=%s",
        user_id, strike_count, DMCA_STRIKE_THRESHOLD, terminate,
    )

    return {
        "strike_id": strike_id,
        "strike_count": int(strike_count),
        "terminate": terminate,
    }


def queue_account_termination(db, user_id: int, reason: str) -> None:
    """将账户加入终止队列，同时写入 banned_users（邮箱 + 注册 IP）。

    """
    # 取用户邮箱与注册 IP
    user_row = db.execute(
        "select email from users where id = %s for update",
        (user_id,),
    ).fetchone()

    email = user_row["email"] if user_row else None
    # The current user schema does not retain a registration IP.
    reg_ip = ""

    # 写入终止队列
    db.execute(
        """
        insert into account_delete_queue (user_id, reason, scheduled_hard_delete_at)
        values (%s, %s, now()+interval '30 days')
        on conflict (user_id) do update
          set reason = excluded.reason, scheduled_hard_delete_at = excluded.scheduled_hard_delete_at, completed_at=null
        """,
        (user_id, reason),
    )

    # 写入永久封禁名单
    if email:
        from .security import normalize_email
        db.execute("delete from banned_users where email_norm=%s", (normalize_email(email),))
        db.execute(
            """
            insert into banned_users (email_norm, ip, reason, banned_at)
            values (%s, %s, %s, now())
            """,
            (normalize_email(email), reg_ip, reason),
        )

    from .federation import revoke_account_tokens
    revoke_account_tokens(db, user_id)

    # 立即停用 sessions，阻止继续登录
    db.execute(
        "delete from sessions where user_id = %s",
        (user_id,),
    )

    # 更新用户状态
    db.execute(
        "update users set deactivated_at = now(), ban_reason = %s where id = %s",
        (reason, user_id),
    )

    log.warning(
        "dmca.terminate user_id=%d email=%s reason=%r",
        user_id, email, reason,
    )

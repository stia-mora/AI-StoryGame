"""Real wallet transactions enforce the ordinary-credit redemption threshold."""
# ruff: noqa: F811 -- pytest fixtures are imported by name.
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from platform_app.db import connect
from platform_app.player import wallet
from tests.integration.test_player_credits import player  # noqa: F401


@pytest.fixture
def coupon(player):
    ids = []

    def create(purpose="player"):
        code = uuid.uuid4().hex.upper()
        with connect() as db:
            cid = db.execute(
                "insert into player_codes(code_hash,label,amount_micro,max_uses,purpose) "
                "values(%s,'Redemption threshold',%s,1,%s) returning id",
                (hashlib.sha256(code.encode()).hexdigest(), 5000 * wallet.MICRO, purpose),
            ).fetchone()["id"]
        ids.append(cid)
        return code, cid

    yield create
    with connect() as db:
        db.execute("delete from player_redemptions where code_id=any(%s)", (ids,))
        db.execute("delete from player_codes where id=any(%s)", (ids,))


def set_balance(uid, free, permanent, held=0):
    with connect() as db:
        wallet.lock_wallet(db, uid)
        db.execute("update player_wallets set free_micro=%s,permanent_micro=%s,held_micro=%s where user_id=%s",
                   (free, permanent, held, uid))


@pytest.mark.parametrize("free,permanent,held,allowed", [
    (0, 4999_000_000, 0, True),
    (0, 5000_000_000, 0, True),
    (1, 5000_000_000, 0, False),
    (100_000_000, 4900_000_000, 1, False),
    (0, 0, 5000_000_001, False),
])
def test_redemption_threshold_preserves_unused_codes(player, coupon, free, permanent, held, allowed):
    uid = player["uid"]
    set_balance(uid, free, permanent, held)
    code, cid = coupon()
    if allowed:
        result = wallet.redeem(uid, code)
        assert result["permanent_micro"] == permanent + 5000 * wallet.MICRO
    else:
        with pytest.raises(HTTPException) as denied:
            wallet.redeem(uid, code)
        assert denied.value.status_code == 409 and "5000" in denied.value.detail
    with connect() as db:
        assert db.execute("select used_count from player_codes where id=%s", (cid,)).fetchone()["used_count"] == int(allowed)
        assert db.execute("select count(*) as n from player_redemptions where code_id=%s", (cid,)).fetchone()["n"] == int(allowed)
        assert db.execute("select count(*) as n from player_ledger where user_id=%s and kind='redeem'", (uid,)).fetchone()["n"] == int(allowed)
        if not allowed:
            current = db.execute("select free_micro,permanent_micro,held_micro from player_wallets where user_id=%s", (uid,)).fetchone()
            assert tuple(current.values()) == (free, permanent, held)


def test_different_codes_cannot_bypass_threshold_with_concurrent_redemption(player, coupon):
    uid = player["uid"]
    set_balance(uid, 0, 5000 * wallet.MICRO)
    codes = [coupon(), coupon()]

    def redeem(value):
        try:
            wallet.redeem(uid, value[0])
            return True
        except HTTPException as exc:
            assert exc.status_code == 409
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(redeem, codes)) == 1
    with connect() as db:
        used = db.execute("select used_count from player_codes where id=any(%s)", ([cid for _, cid in codes],)).fetchall()
        assert sorted(row["used_count"] for row in used) == [0, 1]
        assert db.execute("select permanent_micro from player_wallets where user_id=%s", (uid,)).fetchone()["permanent_micro"] == 10000 * wallet.MICRO


def test_expired_daily_points_do_not_block_redemption(player, coupon):
    uid = player["uid"]
    set_balance(uid, 10000 * wallet.MICRO, 0)
    with connect() as db:
        db.execute("update player_wallets set free_day=free_day-1 where user_id=%s", (uid,))
    result = wallet.redeem(uid, coupon()[0])
    assert result["free_micro"] == 100 * wallet.MICRO
    assert result["permanent_micro"] == 5000 * wallet.MICRO


def test_http_clients_cannot_bypass_the_balance_limit(player, coupon, monkeypatch):
    import app
    from fastapi.testclient import TestClient
    from platform_app.api import _deps

    set_balance(player["uid"], 0, 6000 * wallet.MICRO)
    code, cid = coupon()
    monkeypatch.setattr(_deps, "current_user", lambda request: player["user"])
    client = TestClient(app.app)
    for path in ("/api/player/redeem", "/api/v1/player/redeem"):
        response = client.post(path, json={"code": code})
        assert response.status_code == 409
        assert "请先使用已有积分" in response.json()["detail"]
    with connect() as db:
        assert db.execute("select used_count from player_codes where id=%s", (cid,)).fetchone()["used_count"] == 0


def test_preview_codes_remain_independent_of_the_ordinary_balance_limit(player, coupon):
    uid = player["uid"]
    set_balance(uid, 0, 10000 * wallet.MICRO)
    with connect() as db:
        db.execute("update users set account_mode='creator' where id=%s", (uid,))
    result = wallet.redeem(uid, coupon("preview")[0])
    assert result["preview_micro"] == 15000 * wallet.MICRO
    assert result["permanent_micro"] == 10000 * wallet.MICRO

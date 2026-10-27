"""Serialize memory-intensive package work across the site's web workers."""
from contextlib import contextmanager

from fastapi import HTTPException

from platform_app.db import connect

LOCK_NAME = "authoring:package-memory-budget:v1"


class PackageBusy(HTTPException):
    def __init__(self):
        super().__init__(429, "内容包服务繁忙，请稍后重试", headers={"Retry-After": "30"})


def acquire(db):
    # The transaction holds this lock across PgBouncer transaction pooling.
    # An operator's idle transaction timeout must not release it mid-validation.
    db.execute("set local idle_in_transaction_session_timeout = 0")
    locked = db.execute("select pg_try_advisory_xact_lock(hashtextextended(%s,0)) as owned", (LOCK_NAME,)).fetchone()
    if not locked["owned"]:
        raise PackageBusy()


@contextmanager
def package_budget():
    with connect() as db:
        acquire(db)
        yield

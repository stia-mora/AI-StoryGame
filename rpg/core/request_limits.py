"""API request budgets. Redis shares counters; bounded local fallback covers outages."""
import asyncio
import os
import threading
import time

from fastapi import HTTPException

_lock = threading.Lock()
_windows = {}


def rate_allowed(key, limit, seconds=60):
    import redis_bus

    count = redis_bus.rate_incr(key, seconds)
    if count is not None:
        return count <= limit
    now = time.monotonic()
    with _lock:
        if len(_windows) >= 10000:
            for expired in [k for k, (_, end) in _windows.items() if end <= now]:
                del _windows[expired]
            if key not in _windows and len(_windows) >= 10000:
                return False
        count, end = _windows.get(key, (0, now + seconds))
        if end <= now:
            count, end = 0, now + seconds
        _windows[key] = (count + 1, end)
        return count < limit


async def check(request):
    from platform_app.api._deps import _client_ip

    limit = max(1, int(os.getenv("RPG_RATE_LIMIT_PER_MIN", "600")))
    if not await asyncio.to_thread(rate_allowed, f"http:{_client_ip(request)}", limit):
        raise HTTPException(429, "请求过于频繁，请稍后重试", headers={"Retry-After": "60"})
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    upload = content_type in {"multipart/form-data", "application/zip", "application/octet-stream"}
    cap = int(os.getenv("RPG_UPLOAD_BODY_LIMIT_BYTES" if upload else "RPG_BODY_LIMIT_BYTES",
                        "52428800" if upload else "2097152"))
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(400, "无效的 Content-Length") from None
    if length > cap:
        raise HTTPException(413, "请求内容过大")
    chunks, size = [], 0
    async with asyncio.timeout(float(os.getenv("RPG_REQUEST_TIMEOUT_SECS", "30"))):
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                raise HTTPException(413, "请求内容过大")
            chunks.append(chunk)
    request._body = b"".join(chunks)

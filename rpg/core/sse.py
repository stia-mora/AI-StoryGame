"""core.sse — SSE(Server-Sent Events)帧格式化单一真相源。

`event: <event>\ndata: <json>\n\n` 是 SSE 线格式;全仓所有手写 `_sse`/`_sse_event`
一律委托本函数,避免多份字节级相同实现漂移。
"""
from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any


def sse_frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


SSE_HEADERS = {"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"}


async def with_keepalive(source, interval: float = 15):
    """Keep idle connections open without cancelling the generation on each ping.

    One producer owns the entire iterator, including cleanup, so request ContextVar
    tokens and interrupted-save handlers stay in the task that created them.
    """
    queue = asyncio.Queue(maxsize=1)
    finished = object()

    async def produce():
        try:
            try:
                async for item in source:
                    await queue.put(item)
            finally:
                await source.aclose()
        except Exception as exc:
            await queue.put(exc)
        await queue.put(finished)

    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is finished:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer

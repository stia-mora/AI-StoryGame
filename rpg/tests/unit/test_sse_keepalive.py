import asyncio
from contextvars import ContextVar

import pytest

from core.sse import with_keepalive


async def next_event(stream):
    async def read():
        while True:
            item = await anext(stream)
            if not item.startswith(":"):
                return item

    return await asyncio.wait_for(read(), 1)


def test_idle_pings_do_not_cancel_generation_or_change_its_request_context():
    async def scenario():
        ready = asyncio.Event()
        identity = ContextVar("test_sse_identity", default=None)
        seen = []

        async def source():
            token = identity.set("player-request")
            try:
                seen.append(identity.get())
                yield "event: saving\ndata: {}\n\n"
                await ready.wait()
                seen.append(identity.get())
                yield "event: done\ndata: {}\n\n"
            finally:
                seen.append(identity.get())
                identity.reset(token)

        stream = with_keepalive(source(), interval=0.01)
        assert (await next_event(stream)).startswith("event: saving")
        assert await anext(stream) == ": keepalive\n\n"
        assert await anext(stream) == ": keepalive\n\n"
        assert identity.get() is None
        ready.set()
        assert (await next_event(stream)).startswith("event: done")
        with pytest.raises(StopAsyncIteration):
            await next_event(stream)
        assert seen == ["player-request"] * 3

    asyncio.run(scenario())


def test_disconnect_closes_the_source_and_waits_for_its_save_cleanup():
    async def scenario():
        closed = asyncio.Event()

        async def source():
            try:
                yield "event: token\ndata: {}\n\n"
                await asyncio.Event().wait()
            finally:
                closed.set()

        stream = with_keepalive(source(), interval=0.01)
        await next_event(stream)
        await stream.aclose()
        assert closed.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("during_cleanup", [False, True])
def test_source_or_cleanup_failure_propagates_instead_of_pinging_forever(during_cleanup):
    async def scenario():
        async def source():
            try:
                yield "event: token\ndata: {}\n\n"
                if not during_cleanup:
                    raise ValueError("provider disconnected")
            finally:
                if during_cleanup:
                    raise ValueError("save cleanup failed")

        stream = with_keepalive(source(), interval=0.01)
        await next_event(stream)
        with pytest.raises(ValueError):
            await next_event(stream)

    asyncio.run(scenario())

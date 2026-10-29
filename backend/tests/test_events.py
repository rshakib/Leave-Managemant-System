"""The in-process change broadcaster behind the SSE stream."""

import asyncio

from app.services import events


def test_a_subscriber_receives_every_publish_in_order():
    async def scenario():
        queue = events.subscribe()
        try:
            first = events.publish()
            second = events.publish()
            got = [queue.get_nowait(), queue.get_nowait()]
            return first, second, got
        finally:
            events.unsubscribe(queue)

    first, second, got = asyncio.run(scenario())
    assert got == [first, second]
    assert second == first + 1


def test_unsubscribing_stops_delivery():
    async def scenario():
        queue = events.subscribe()
        events.unsubscribe(queue)
        events.publish()
        return queue.empty()

    assert asyncio.run(scenario()) is True


def test_a_slow_subscriber_never_blocks_the_writer():
    async def scenario():
        queue = events.subscribe()
        try:
            for _ in range(20):          # queue is bounded at 8
                events.publish()
            return True
        finally:
            events.unsubscribe(queue)

    assert asyncio.run(scenario()) is True

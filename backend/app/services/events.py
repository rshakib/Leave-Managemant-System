import asyncio

_subscribers: set[asyncio.Queue] = set()
_version = 0


def version() -> int:
    return _version


def publish() -> int:
    global _version
    _version += 1
    for queue in list(_subscribers):
        try:
            queue.put_nowait(_version)
        except asyncio.QueueFull:
            pass
    return _version


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def subscriber_count() -> int:
    return len(_subscribers)

import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.services import events

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 25


@router.get("/events")
async def stream_changes():
    async def generator():
        queue = events.subscribe()
        try:
            yield f"event: ready\ndata: {events.version()}\n\n"
            while True:
                try:
                    number = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {number}\n\n"
        finally:
            events.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

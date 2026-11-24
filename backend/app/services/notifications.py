"""Phase 6 (P6-1): a real, durable `Notification` row per genuine event
(created by `app/services/task_execution.py` and
`app/services/workflow_execution.py` at actual completion/failure/handoff
points -- never a placeholder feed), plus best-effort live delivery over a
per-user WebSocket, mirroring `app/services/presence.py`'s pattern.

The durable row is the source of truth: `GET /notifications` always
reflects it regardless of whether the live push ever reached anyone. The
live push is a genuine addition on top, not a substitute -- it is
one-way, fire-and-forget, and never raises into the caller (background
task-execution threads must not fail a real task run over a notification
delivery problem).

Creating a notification happens from ordinary synchronous code running in
a background thread (task/workflow execution), not inside the asyncio
event loop that serves the WebSocket. `push_threadsafe` bridges that gap
with `asyncio.run_coroutine_threadsafe` against the real loop the app
bound at startup -- it is a no-op (never blocks, never raises) when no
loop has been bound yet or nothing is actually connected for that user.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession
from starlette.websockets import WebSocket

from app.models.notification import Notification


class NotificationManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, dict[str, WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def join(self, user_id: uuid.UUID, connection_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(user_id, {})[connection_id] = websocket

    async def leave(self, user_id: uuid.UUID, connection_id: str) -> None:
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns is not None:
                conns.pop(connection_id, None)
                if not conns:
                    self._connections.pop(user_id, None)

    async def _push(self, user_id: uuid.UUID, payload: dict) -> None:
        async with self._lock:
            sockets = list(self._connections.get(user_id, {}).items())
        stale: list[str] = []
        for connection_id, websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(connection_id)
        if stale:
            async with self._lock:
                remaining = self._connections.get(user_id)
                if remaining is not None:
                    for connection_id in stale:
                        remaining.pop(connection_id, None)
                    if not remaining:
                        self._connections.pop(user_id, None)

    def push_threadsafe(self, user_id: uuid.UUID, payload: dict) -> None:
        if self._loop is None:
            return
        coroutine = self._push(user_id, payload)
        try:
            asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except RuntimeError:
            # The loop is shutting down (e.g. during test teardown) -- a
            # missed live push is never worth failing real work over.
            # Close the never-scheduled coroutine explicitly so Python
            # doesn't warn about it being garbage-collected unawaited.
            coroutine.close()


notification_manager = NotificationManager()


def create_notification(
    db: DBSession,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    body: str = "",
    link_url: str = "",
    organization_id: uuid.UUID | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        organization_id=organization_id,
        type=type,
        title=title,
        body=body,
        link_url=link_url,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    notification_manager.push_threadsafe(
        user_id,
        {
            "id": str(notification.id),
            "type": notification.type,
            "title": notification.title,
            "body": notification.body,
            "link_url": notification.link_url,
            "created_at": notification.created_at.isoformat(),
        },
    )
    return notification


def mark_read(db: DBSession, notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification

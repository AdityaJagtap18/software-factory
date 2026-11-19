"""Tracks who currently has a project workspace open, so every connected
viewer can be shown real, live presence — not a simulated "3 people
online" counter. Backed by actual open WebSocket connections: a viewer
appears the instant their socket connects and disappears the instant it
closes (browser tab closed, network drop, navigation away).

In-memory and per-process: this is honest for the single backend process
this stack runs as. It does not claim to coordinate presence across
multiple backend replicas — that would require a shared pub/sub (e.g.
Redis) this pass does not add.
"""

import asyncio
import uuid
from dataclasses import dataclass

from starlette.websockets import WebSocket


@dataclass
class _Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    full_name: str


class PresenceManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, dict[str, _Connection]] = {}
        self._lock = asyncio.Lock()

    async def join(
        self, project_id: uuid.UUID, connection_id: str, websocket: WebSocket, user_id: uuid.UUID, full_name: str
    ) -> None:
        async with self._lock:
            self._connections.setdefault(project_id, {})[connection_id] = _Connection(
                websocket, user_id, full_name
            )
        await self._broadcast(project_id)

    async def leave(self, project_id: uuid.UUID, connection_id: str) -> None:
        async with self._lock:
            conns = self._connections.get(project_id)
            if conns is not None:
                conns.pop(connection_id, None)
                if not conns:
                    self._connections.pop(project_id, None)
        await self._broadcast(project_id)

    def _viewer_payload(self, project_id: uuid.UUID) -> list[dict]:
        conns = self._connections.get(project_id, {})
        seen: dict[uuid.UUID, str] = {}
        for conn in conns.values():
            seen[conn.user_id] = conn.full_name
        return [{"user_id": str(uid), "full_name": name} for uid, name in seen.items()]

    async def _broadcast(self, project_id: uuid.UUID) -> None:
        async with self._lock:
            conns = list(self._connections.get(project_id, {}).items())
            payload = {"viewers": self._viewer_payload(project_id)}
        stale: list[str] = []
        for connection_id, conn in conns:
            try:
                await conn.websocket.send_json(payload)
            except Exception:
                stale.append(connection_id)
        if stale:
            async with self._lock:
                remaining = self._connections.get(project_id)
                if remaining is not None:
                    for connection_id in stale:
                        remaining.pop(connection_id, None)
                    if not remaining:
                        self._connections.pop(project_id, None)


presence_manager = PresenceManager()

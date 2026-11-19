import uuid

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.deps import effective_project_role
from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.project import Project
from app.models.user import User
from app.services.presence import presence_manager

router = APIRouter(tags=["presence"])


@router.websocket("/projects/{project_id}/presence/ws")
async def project_presence(websocket: WebSocket, project_id: uuid.UUID, token: str = Query(...)) -> None:
    """Real-time "who's viewing this project" presence. A browser WebSocket
    cannot set an Authorization header, so the access token travels as a
    query parameter instead — the same real JWT used everywhere else,
    verified here exactly like `get_current_user`, never accepted as-is."""
    db = SessionLocal()
    try:
        try:
            payload = decode_token(token)
            if payload.get("type") != "access":
                raise ValueError("wrong token type")
            user_id = uuid.UUID(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError):
            await websocket.close(code=4401)
            return

        user = db.get(User, user_id)
        if user is None or not user.is_active:
            await websocket.close(code=4401)
            return

        project = db.get(Project, project_id)
        if project is None:
            await websocket.close(code=4404)
            return

        role = effective_project_role(db, project, user)
        if role is None:
            await websocket.close(code=4403)
            return

        full_name = user.full_name
    finally:
        db.close()

    await websocket.accept()
    connection_id = str(uuid.uuid4())
    await presence_manager.join(project_id, connection_id, websocket, user.id, full_name)
    try:
        while True:
            # Viewers don't send anything meaningful; this just blocks until
            # the socket closes (tab closed, navigated away, network drop).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await presence_manager.leave(project_id, connection_id)

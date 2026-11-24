import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session as DBSession

from app.api.deps import get_current_user
from app.core.database import SessionLocal, get_db
from app.core.security import decode_token
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationResponse
from app.services import notifications as notification_service
from app.services.notifications import notification_manager

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationResponse])
def list_my_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[NotificationResponse]:
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


@router.get("/notifications/unread-count")
def unread_notification_count(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict:
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )
    return {"count": count}


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> NotificationResponse:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return notification_service.mark_read(db, notification)


@router.websocket("/notifications/ws")
async def notifications_ws(websocket: WebSocket, token: str = Query(...)) -> None:
    """Live delivery (P6-1): the same real-JWT-as-query-param pattern used
    by `app/api/routes/presence.py`'s WebSocket, since a browser socket
    can't set an Authorization header."""
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
    finally:
        db.close()

    await websocket.accept()
    connection_id = str(uuid.uuid4())
    await notification_manager.join(user.id, connection_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await notification_manager.leave(user.id, connection_id)

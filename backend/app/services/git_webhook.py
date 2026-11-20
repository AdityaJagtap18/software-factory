"""Inbound GitHub webhook handling.

A webhook's *receipt* is never, by itself, recorded as a successful
sync -- `process_event` always persists the real downstream outcome in
`processing_result`. Processing is idempotent: a redelivered event (same
`provider_delivery_id`) is recognized and not reprocessed, because of the
unique constraint on `(provider, provider_delivery_id)`.
"""

import hashlib
import hmac
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models.git_integration import (
    GitProvider,
    RepositoryConnection,
    RepositoryConnectionStatus,
    WebhookEvent,
)

# Event types this phase actually acts on. Branch create/delete, pull-request
# lifecycle, and CI/check-status events are received and recorded (never
# silently dropped) but their deeper handling is later roadmap scope (PR
# lifecycle lands in Phase 15) -- recorded here rather than claimed as done.
_METADATA_SYNC_EVENTS = {"push"}


def verify_signature(secret: str, payload: bytes, signature_header: str | None) -> bool:
    """A real HMAC-SHA256 comparison against GitHub's `X-Hub-Signature-256`
    header. No secret configured, no header present, or a mismatch all
    return False -- an unverifiable signature is never treated as valid."""
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = signature_header[len("sha256=") :]
    return hmac.compare_digest(expected, provided)


def _find_connections(db: DBSession, full_name: str) -> list[RepositoryConnection]:
    if not full_name:
        return []
    return db.query(RepositoryConnection).filter_by(full_name=full_name).all()


def process_event(
    db: DBSession,
    *,
    event_type: str,
    delivery_id: str,
    signature_verified: bool,
    payload: dict,
) -> WebhookEvent:
    full_name = (payload.get("repository") or {}).get("full_name", "")

    existing = (
        db.query(WebhookEvent)
        .filter_by(provider=GitProvider.GITHUB, provider_delivery_id=delivery_id)
        .first()
    )
    if existing is not None:
        return existing  # Already processed this exact delivery -- never twice.

    event = WebhookEvent(
        provider=GitProvider.GITHUB,
        provider_delivery_id=delivery_id,
        event_type=event_type,
        repository_full_name=full_name,
        signature_verified=signature_verified,
    )

    if not signature_verified:
        event.processing_result = "rejected: invalid or missing signature"
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent redelivery raced us to the unique constraint.
            db.rollback()
            return (
                db.query(WebhookEvent)
                .filter_by(provider=GitProvider.GITHUB, provider_delivery_id=delivery_id)
                .first()
            )
        return event

    connections = _find_connections(db, full_name)
    if not connections:
        event.processing_result = "recorded: no matching repository connection"
    elif event_type not in _METADATA_SYNC_EVENTS:
        event.processing_result = f"recorded: '{event_type}' event type handling not yet implemented"
    else:
        after_sha = payload.get("after", "")
        ref = payload.get("ref", "")
        for connection in connections:
            connection.last_observed_commit_sha = after_sha
            connection.last_successful_sync_at = datetime.now(timezone.utc)
            connection.status = RepositoryConnectionStatus.CONNECTED
            connection.last_error = ""
            if connection.default_branch and ref == f"refs/heads/{connection.default_branch}":
                pass  # Default branch's head commit just moved; nothing else to update yet.
        event.processing_result = f"synced {len(connections)} repository connection(s)"
        event.repository_connection_id = connections[0].id

    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (
            db.query(WebhookEvent)
            .filter_by(provider=GitProvider.GITHUB, provider_delivery_id=delivery_id)
            .first()
        )
    db.refresh(event)
    return event


def verify_request_signature(raw_body: bytes, signature_header: str | None) -> bool:
    return verify_signature(get_settings().github_webhook_secret, raw_body, signature_header)

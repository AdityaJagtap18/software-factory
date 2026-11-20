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
from app.models.task import Task

# Event types this phase actually acts on. Branch create/delete events
# are received and recorded (never silently dropped) but their deeper
# handling is later roadmap scope -- recorded here rather than claimed as
# done. `push` (Phase 13), `pull_request` (Phase 16), and `check_suite`
# (Phase 17) are genuinely handled below.
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


def _apply_pull_request_event(
    db: DBSession, connections: list[RepositoryConnection], payload: dict
) -> str:
    """Phase 16: keeps the originating task's `git_pr_state` in sync with
    GitHub's own real pull-request state ("open", "closed", or "merged").
    Matched only by PR number within the connected project(s) -- never
    guessed from the branch name or timing. A PR GitHub opened some other
    way (not via Phase 15) matches no task and is recorded as such."""
    pr = payload.get("pull_request") or {}
    pr_number = pr.get("number")
    if not pr_number:
        return "recorded: pull_request event missing a PR number"

    state = "merged" if pr.get("merged") else pr.get("state", "")
    project_ids = [c.project_id for c in connections]
    tasks = (
        db.query(Task)
        .filter(Task.project_id.in_(project_ids), Task.git_pr_number == pr_number)
        .all()
    )
    for task in tasks:
        task.git_pr_state = state
    if not tasks:
        return f"recorded: pull_request #{pr_number} matches no task opened by this backend"
    return f"updated pull request state to '{state}' on {len(tasks)} task(s)"


def _apply_check_suite_event(
    db: DBSession, connections: list[RepositoryConnection], payload: dict
) -> str:
    """Phase 17: keeps the originating task's `git_ci_status` in sync with
    GitHub's own real CI result for its branch -- a real conclusion
    ("success", "failure", ...) once GitHub's check suite completes, or
    its real in-progress `status` ("queued"/"in_progress") before that.
    Matched by the real head branch within the connected project(s) --
    never run or simulated by this backend itself."""
    suite = payload.get("check_suite") or {}
    head_branch = suite.get("head_branch", "")
    if not head_branch:
        return "recorded: check_suite event missing a head branch"

    ci_status = suite.get("conclusion") or suite.get("status") or ""
    project_ids = [c.project_id for c in connections]
    tasks = (
        db.query(Task)
        .filter(Task.project_id.in_(project_ids), Task.git_branch_name == head_branch)
        .all()
    )
    for task in tasks:
        task.git_ci_status = ci_status
    if not tasks:
        return f"recorded: check_suite for branch '{head_branch}' matches no task opened by this backend"
    return f"updated CI status to '{ci_status}' on {len(tasks)} task(s)"


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
    elif event_type == "pull_request":
        event.processing_result = _apply_pull_request_event(db, connections, payload)
        event.repository_connection_id = connections[0].id
    elif event_type == "check_suite":
        event.processing_result = _apply_check_suite_event(db, connections, payload)
        event.repository_connection_id = connections[0].id
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

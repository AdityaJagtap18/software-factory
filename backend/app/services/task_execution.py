"""Runs a task against a coding-agent connection, streaming real output into
the task row as it arrives — used both for a standalone task start (its own
background thread + DB session) and for each step of a workflow (run
sequentially within the workflow's own background thread/session, see
`app/services/workflow_execution.py`).

Non-negotiable: a task is only ever marked `completed` when the adapter's
`start_execution_streaming` actually returned `succeeded=True` from a real
CLI invocation or a real provider API call. Every other path — no
connection assigned, connection not currently connected, adapter failure,
user cancellation — marks the task `failed` with the real reason and
whatever partial output was genuinely produced, never a fabricated success.

Phase 14: when the project has a real connected repository, the task runs
inside its own isolated Git worktree/branch (`app/services/git_worktree.py`)
instead of a bare prompt with no codebase, and the real resulting diff is
captured on the task row.

Phase 15: once that task actually changed files, its branch is pushed to
the real remote and a real pull request is opened from it via the Git
Provider Interface -- never a fabricated PR number or URL, and a push/PR
failure never overturns the adapter's own success/failure verdict.

Phase 16: the PR's state recorded here (`git_pr_state`) is only the
initial "open" -- it is kept in sync with the PR's real lifecycle
(merged/closed) by GitHub's own `pull_request` webhook, handled in
`app/services/git_webhook.py`, never inferred or polled from here.

Phase 18: right after opening the PR, this backend asks GitHub for the
base branch's real branch protection rules and records them for display
-- informational only. This backend never enforces or bypasses them;
GitHub's own merge button is what actually requires them.
"""

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from app.core.crypto import decrypt_value
from app.core.database import SessionLocal
from app.models.agent_runtime import CodingAgentConnection, Credential
from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.task import Task, TaskStatus
from app.services import git_worktree
from app.services.agent_runtime.registry import get_adapter
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider

_OUTPUT_COMMIT_INTERVAL = 20  # flush to the DB at least every N chunks


def start_task_in_background(task_id: uuid.UUID) -> None:
    thread = threading.Thread(target=_run, args=(task_id,), daemon=True)
    thread.start()


def execute_task(
    db: DBSession, task: Task, extra_should_cancel: Callable[[], bool] | None = None
) -> None:
    """Runs `task` to completion against its assigned connection, committing
    real progress to `db` as it happens. Leaves `task.status` as COMPLETED
    or FAILED. Does not open or close `db` — the caller owns the session."""
    task.started_at = datetime.now(timezone.utc)
    db.commit()

    if task.coding_agent_connection_id is None:
        task.status = TaskStatus.FAILED
        task.error_message = "No coding-agent connection assigned to this task."
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    connection = db.get(CodingAgentConnection, task.coding_agent_connection_id)
    adapter = get_adapter(connection.runtime_slug) if connection else None
    if connection is None or adapter is None:
        task.status = TaskStatus.FAILED
        task.error_message = "Assigned coding-agent connection no longer exists."
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    credential_value = None
    if connection.credential_id is not None:
        credential = db.get(Credential, connection.credential_id)
        if credential is not None:
            credential_value = decrypt_value(credential.encrypted_value)

    # Re-check connectivity right before running — a cached "connected"
    # status from an earlier health check could be stale.
    health = adapter.health_check(credential_value)
    if not health.connected:
        task.status = TaskStatus.FAILED
        task.error_message = f"{adapter.display_name} is not connected: {health.detail}"
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    # Phase 14: when the project has a real connected repository, run this
    # task against an isolated, real Git worktree/branch instead of a bare
    # prompt with no codebase. No connection means no worktree — exactly
    # the same behavior as before this phase, never a fabricated one.
    worktree: git_worktree.WorktreeResult | None = None
    connection_record = (
        db.query(RepositoryConnection)
        .filter(
            RepositoryConnection.project_id == task.project_id,
            RepositoryConnection.status == RepositoryConnectionStatus.CONNECTED,
        )
        .first()
    )
    if connection_record is not None:
        try:
            worktree = git_worktree.prepare_worktree(task, connection_record)
            task.git_branch_name = worktree.branch_name
            task.git_base_branch = worktree.base_branch
            db.commit()
        except git_worktree.WorktreeError as exc:
            task.status = TaskStatus.FAILED
            task.error_message = f"Could not prepare a Git worktree for this task: {exc.detail}"
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

    chunk_count = 0

    def on_chunk(text: str) -> None:
        nonlocal chunk_count
        task.output = (task.output or "") + text
        chunk_count += 1
        if chunk_count % _OUTPUT_COMMIT_INTERVAL == 0:
            db.commit()

    def should_cancel() -> bool:
        db.refresh(task, attribute_names=["cancel_requested"])
        if task.cancel_requested:
            return True
        return extra_should_cancel() if extra_should_cancel else False

    result = adapter.start_execution_streaming(
        task.description or task.title,
        credential_value,
        on_chunk,
        should_cancel,
        cwd=worktree.path if worktree else None,
    )
    task.completed_at = datetime.now(timezone.utc)
    if result.succeeded:
        task.status = TaskStatus.COMPLETED
        task.output = result.output
        task.error_message = ""
    else:
        task.status = TaskStatus.FAILED
        task.output = result.output or task.output
        task.error_message = result.error

    if worktree is not None:
        try:
            diff = git_worktree.collect_diff(worktree.path, task.title)
            task.git_changed_files = diff.changed_files
            task.git_diff = diff.diff_text
        except git_worktree.WorktreeError as exc:
            # Never overturn the adapter's own real success/failure verdict
            # over a diff-collection problem -- just note it honestly.
            note = f"Task output recorded, but could not collect the git diff: {exc.detail}"
            task.error_message = f"{task.error_message} ({note})" if task.error_message else note
            diff = None

        # Phase 15: a task that actually changed files gets its branch
        # pushed and a real pull request opened from it -- never a
        # fabricated PR number/URL, and never overturning the task's own
        # success/failure verdict over a push/PR problem.
        if diff is not None and diff.changed_files and connection_record is not None:
            try:
                git_worktree.push_branch(worktree.path, worktree.branch_name, worktree.clone_secret)
                provider = get_git_provider(connection_record.installation.provider.value)
                pr = provider.create_pull_request(
                    connection_record.installation.external_installation_id,
                    connection_record.owner,
                    connection_record.name,
                    worktree.branch_name,
                    worktree.base_branch,
                    task.title,
                    task.description or "",
                )
                task.git_pr_url = pr.url
                task.git_pr_number = pr.number
                task.git_pr_state = pr.state
                try:
                    protection = provider.get_branch_protection(
                        connection_record.installation.external_installation_id,
                        connection_record.owner,
                        connection_record.name,
                        worktree.base_branch,
                    )
                    task.git_base_branch_protected = protection.protected
                    task.git_required_status_checks = protection.required_status_checks
                    task.git_required_approving_reviews = protection.required_approving_review_count
                except GitProviderError as exc:
                    # Informational only -- never overturn the PR that was
                    # already opened successfully over this lookup failing.
                    note = f"Pull request opened, but could not read the base branch's protection rules: {exc.detail}"
                    task.error_message = f"{task.error_message} ({note})" if task.error_message else note
            except (git_worktree.WorktreeError, GitProviderError) as exc:
                note = f"Task output recorded, but could not open a pull request: {exc.detail}"
                task.error_message = f"{task.error_message} ({note})" if task.error_message else note
    db.commit()


def _run(task_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        execute_task(db, task)
    finally:
        db.close()

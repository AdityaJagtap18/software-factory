"""Phase 5 (P5-2): agent replacement and resumable handoff.

The example the roadmap gives is the test: "Claude Code begins
implementation -> execution encounters a failure or provider becomes
unavailable -> Codex takes over -> Codex resumes from the saved handover
state." This module is that path. It deliberately continues the SAME
engineering objective rather than restarting:

- The same Git worktree/branch is resumed (`git_worktree.resume_worktree`)
  -- the new agent sees the exact files the previous one left behind, same
  as a same-agent follow-up turn (P3-4's `execute_followup`), just with a
  different adapter attached.
- The new agent's prompt is built from a real handover package
  (`build_handover_package`) -- the original instruction, what was
  genuinely completed, the real failure/remaining-work reason, real test
  results, and real review comments -- not a bare "try again" with no
  context.
- Every handoff is an immutable, versioned `TaskHandoff` row (never
  overwritten), and the resulting execution is its own immutable
  `TaskExecutionAttempt` row linked back to it -- the full
  replace/fallback history is reconstructable afterward.

Honest limitation, matching `audit/03-AGENT_ORCHESTRATION_AUDIT.md` B9: no
adapter today (Claude Code CLI, Codex CLI, Gemini CLI, Qwen CLI, or the
HTTP-based provider calls) exposes a resumable native session/thread ID --
every invocation is a fresh, stateless process or API call. So
`provider_session_id` in the handover package is always null; this module
only implements the "context-based continuation" path the roadmap
explicitly allows as the fallback when native resume isn't available. If a
future adapter does add real session-ID support, that ID belongs in this
same package, not a parallel mechanism.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.core.crypto import decrypt_value
from app.core.database import SessionLocal
from app.models.agent_runtime import CodingAgentConnection, Credential
from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.orchestration import HandoffStatus, TaskExecutionAttempt, TaskHandoff
from app.models.review_comment import ReviewComment
from app.models.task import Task, TaskStatus
from app.models.task_message import TaskMessage, TaskMessageRole
from app.models.test_run import TestRun
from app.services import git_worktree
from app.services.agent_runtime.registry import get_adapter

_DIFF_EXCERPT_CHARS = 20_000
_OUTPUT_EXCERPT_CHARS = 20_000


class HandoffError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def build_handover_package(db: DBSession, task: Task) -> dict:
    """A real, honest snapshot of everything this task has genuinely
    produced so far -- never fabricated, never a live reference that could
    drift after this call returns (the whole point of a *versioned*
    handover package)."""
    test_runs = (
        db.query(TestRun).filter_by(task_id=task.id).order_by(TestRun.created_at.desc()).all()
    )
    review_comments = (
        db.query(ReviewComment)
        .filter_by(task_id=task.id)
        .order_by(ReviewComment.created_at.asc())
        .all()
    )
    messages = (
        db.query(TaskMessage).filter_by(task_id=task.id).order_by(TaskMessage.created_at.asc()).all()
    )
    attempts = (
        db.query(TaskExecutionAttempt)
        .filter_by(task_id=task.id)
        .order_by(TaskExecutionAttempt.started_at.asc())
        .all()
    )
    return {
        "task_id": str(task.id),
        "title": task.title,
        "original_instruction": task.description or task.title,
        "git_branch_name": task.git_branch_name,
        "git_base_branch": task.git_base_branch,
        "git_changed_files": list(task.git_changed_files or []),
        "git_diff_excerpt": (task.git_diff or "")[:_DIFF_EXCERPT_CHARS],
        "completed_work_output": (task.output or "")[:_OUTPUT_EXCERPT_CHARS],
        "known_failure_reason": task.error_message or "",
        "test_results": [
            {
                "framework": tr.framework.value,
                "ran": tr.ran,
                "passed": tr.passed,
                "failed": tr.failed,
                "total": tr.total,
            }
            for tr in test_runs
        ],
        "review_comments": [
            {
                "body": c.body,
                "file_path": c.file_path,
                "line_number": c.line_number,
                "resolved": c.resolved,
            }
            for c in review_comments
        ],
        "conversation": [{"role": m.role.value, "content": m.content} for m in messages],
        "prior_attempts": [
            {
                "agent_slug": a.agent_slug,
                "succeeded": a.succeeded,
                "error_message": a.error_message,
            }
            for a in attempts
        ],
        # Honest null -- see module docstring: no adapter exposes a real
        # resumable session ID today.
        "provider_session_id": None,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }


def create_handoff(
    db: DBSession,
    task: Task,
    to_connection_id: uuid.UUID,
    reason: str,
    triggered_by_user_id: uuid.UUID | None = None,
    automatic: bool = False,
) -> TaskHandoff:
    """Records a new, immutable, versioned handover package. Any still-
    `PENDING` handoff on this task is superseded (not deleted) first, so a
    second handoff created before the first was ever resumed doesn't leave
    two "pending" rows claiming the same in-flight replacement."""
    db.query(TaskHandoff).filter(
        TaskHandoff.task_id == task.id, TaskHandoff.status == HandoffStatus.PENDING
    ).update({"status": HandoffStatus.SUPERSEDED})

    next_attempt_number = (
        db.query(func.max(TaskHandoff.attempt_number)).filter(TaskHandoff.task_id == task.id).scalar()
        or 0
    ) + 1

    handoff = TaskHandoff(
        task_id=task.id,
        attempt_number=next_attempt_number,
        from_connection_id=task.coding_agent_connection_id,
        to_connection_id=to_connection_id,
        reason=reason,
        triggered_by_user_id=triggered_by_user_id,
        automatic=automatic,
        status=HandoffStatus.PENDING,
        package=build_handover_package(db, task),
    )
    db.add(handoff)
    db.commit()
    db.refresh(handoff)
    return handoff


def _render_continuation_prompt(package: dict, instruction: str | None) -> str:
    """A single flowing instruction, not a multi-paragraph "context" block
    -- P3-4's `execute_followup` already found (empirically, documented
    there) that real coding-agent CLIs respond far better to one real
    continuation sentence than a formatted dump. The real detail (test
    results, review comments, failure reason) is still folded in as plain
    clauses, not dropped."""
    parts = [
        "A different coding agent already worked on this task in this exact "
        "repository checkout -- the real changes are already on disk, continue "
        "in it, don't start over."
    ]
    if package.get("known_failure_reason"):
        parts.append(f"The previous agent stopped because: {package['known_failure_reason']}.")
    failing = [t for t in package.get("test_results", []) if t.get("ran") and t.get("failed")]
    if failing:
        worst = failing[0]
        parts.append(
            f"The real test run showed {worst['failed']} of {worst['total']} tests failing "
            f"({worst['framework']}) -- fix those too."
        )
    open_comments = [c for c in package.get("review_comments", []) if not c.get("resolved")]
    if open_comments:
        parts.append(f"There are {len(open_comments)} unresolved review comment(s) to address.")
    parts.append(f"The original task: {package.get('original_instruction', '')}.")
    if instruction:
        parts.append(f"Additional instruction for this handoff: {instruction}")
    return " ".join(parts)


def resume_task_with_handoff(
    db: DBSession,
    task: Task,
    handoff: TaskHandoff,
    instruction: str | None = None,
    extra_should_cancel: Callable[[], bool] | None = None,
) -> None:
    """Resumes `task` under the connection named by `handoff.to_connection_id`,
    using the SAME Git worktree/branch, with a prompt built from the real
    handover package -- a genuine continuation, never a stateless restart.
    Leaves `task.status` as COMPLETED or FAILED, same contract as
    `task_execution.execute_task`/`execute_followup`. Caller owns `db`."""
    from app.services import task_execution  # local import: avoids a circular import at module load

    task.status = TaskStatus.RUNNING
    task.cancel_requested = False
    db.commit()

    def fail(message: str) -> None:
        task.status = TaskStatus.FAILED
        task.error_message = message
        task.completed_at = datetime.now(timezone.utc)
        db.add(TaskMessage(task_id=task.id, role=TaskMessageRole.SYSTEM, content=message))
        db.commit()

    if not task.git_branch_name:
        fail("This task has no existing workspace to hand off into — start it at least once first.")
        return

    connection = db.get(CodingAgentConnection, handoff.to_connection_id)
    adapter = get_adapter(connection.runtime_slug) if connection else None
    if connection is None or adapter is None:
        fail("The connection named in this handoff no longer exists.")
        return

    credential_value = None
    if connection.credential_id is not None:
        credential = db.get(Credential, connection.credential_id)
        if credential is not None:
            credential_value = decrypt_value(credential.encrypted_value)

    health = adapter.health_check(credential_value)
    if not health.connected:
        fail(f"{adapter.display_name} is not connected: {health.detail}")
        return

    connection_record = (
        db.query(RepositoryConnection)
        .filter(
            RepositoryConnection.project_id == task.project_id,
            RepositoryConnection.status == RepositoryConnectionStatus.CONNECTED,
        )
        .first()
    )
    if connection_record is None:
        fail("This project's repository connection is no longer available.")
        return

    try:
        worktree = git_worktree.resume_worktree(task, connection_record)
    except git_worktree.WorktreeError as exc:
        fail(f"Could not resume this task's Git workspace for the handoff: {exc.detail}")
        return

    prompt = _render_continuation_prompt(handoff.package, instruction)

    task.coding_agent_connection_id = connection.id
    db.add(
        TaskMessage(
            task_id=task.id,
            role=TaskMessageRole.SYSTEM,
            content=f"Handed off to {adapter.display_name} ({handoff.reason or 'manual reassignment'}).",
        )
    )
    db.commit()

    task_execution._run_adapter_and_finish(
        db, task, adapter, credential_value, prompt, worktree, connection_record,
        extra_should_cancel, agent_connection=connection, handoff_id=handoff.id,
    )

    handoff.status = HandoffStatus.RESUMED
    db.commit()

    if task.status == TaskStatus.COMPLETED:
        db.add(TaskMessage(task_id=task.id, role=TaskMessageRole.AGENT, content=task.output or ""))
    else:
        db.add(
            TaskMessage(
                task_id=task.id,
                role=TaskMessageRole.SYSTEM,
                content=task.error_message or "The handed-off run failed.",
            )
        )
    db.commit()


def start_handoff_in_background(task_id: uuid.UUID, handoff_id: uuid.UUID, instruction: str | None) -> None:
    thread = threading.Thread(
        target=_run_handoff, args=(task_id, handoff_id, instruction), daemon=True
    )
    thread.start()


def _run_handoff(task_id: uuid.UUID, handoff_id: uuid.UUID, instruction: str | None) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        handoff = db.get(TaskHandoff, handoff_id)
        if task is None or handoff is None:
            return
        resume_task_with_handoff(db, task, handoff, instruction)
    finally:
        db.close()

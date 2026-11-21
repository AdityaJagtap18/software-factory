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
from app.models.approval import Approval, ApprovalCategory, ApprovalPriority
from app.models.git_integration import RepositoryConnection, RepositoryConnectionStatus
from app.models.orchestration import TaskExecutionAttempt
from app.models.task import Task, TaskStatus
from app.models.task_message import TaskMessage, TaskMessageRole
from app.services import git_worktree, test_execution
from app.services.agent_runtime.registry import get_adapter
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider

_OUTPUT_COMMIT_INTERVAL = 20  # flush to the DB at least every N chunks


def _start_attempt(
    db: DBSession,
    task: Task,
    connection: CodingAgentConnection | None,
    handoff_id: uuid.UUID | None = None,
) -> TaskExecutionAttempt:
    """P5-2: the immutable record of this one real adapter invocation,
    created right before it actually happens -- never after, so a crash
    mid-execution still leaves an honest "started, never finished" row
    rather than a gap in the attempt history."""
    attempt = TaskExecutionAttempt(
        task_id=task.id,
        connection_id=connection.id if connection else None,
        agent_slug=connection.runtime_slug if connection else "",
        handoff_id=handoff_id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _finish_attempt(db: DBSession, attempt: TaskExecutionAttempt, task: Task) -> None:
    """Deliberately does NOT commit: `task.status` is set to its terminal
    value right before this is called, and committing here would let a
    polling caller observe a "completed"/"failed" task before the diff
    collection and PR push/update below have actually run -- the same
    invariant `_run_adapter_and_finish`'s own final `db.commit()` already
    protects for the test-execution step. The caller's single trailing
    commit covers this row too."""
    attempt.completed_at = datetime.now(timezone.utc)
    attempt.succeeded = task.status == TaskStatus.COMPLETED
    attempt.error_message = task.error_message or ""


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

    _run_adapter_and_finish(
        db, task, adapter, credential_value, _build_prompt_with_rag_context(db, task),
        worktree, connection_record, extra_should_cancel, agent_connection=connection,
    )


def _build_prompt_with_rag_context(db: DBSession, task: Task) -> str:
    """P4-4: prepends real RAG retrieval over this project's ingested
    documents (see app/services/document_retrieval.py) to the task prompt.
    Returns the bare instruction unchanged when the project has no
    documents or the local embedding model is unreachable -- never blocks
    or fabricates context, it's a pure addition."""
    user_instruction = task.description or task.title
    from app.services import document_retrieval
    rag_context = document_retrieval.build_rag_context(db, task.project_id, user_instruction)
    if rag_context:
        return f"{rag_context}\n\nTASK INSTRUCTION:\n{user_instruction}"
    return user_instruction


def _run_adapter_and_finish(
    db: DBSession,
    task: Task,
    adapter,
    credential_value: str | None,
    prompt: str,
    worktree: "git_worktree.WorktreeResult | None",
    connection_record: RepositoryConnection | None,
    extra_should_cancel: Callable[[], bool] | None,
    agent_connection: CodingAgentConnection | None = None,
    handoff_id: uuid.UUID | None = None,
) -> None:
    """Shared tail of both a fresh task run and a follow-up turn: stream the
    adapter's real output into `task.output`, then (if there's a worktree)
    collect the real cumulative diff and push/open-or-update a real PR.
    Leaves `task.status` as COMPLETED or FAILED. Caller owns the session.

    P5-2: `agent_connection`/`handoff_id` are only for the
    `TaskExecutionAttempt` audit row (who actually ran this, and whether it
    was a resumed handoff) -- they never change execution behavior."""
    chunk_count = 0
    attempt = _start_attempt(db, task, agent_connection, handoff_id)

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
        prompt,
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
    _finish_attempt(db, attempt, task)

    if worktree is not None:
        try:
            diff = git_worktree.collect_diff(worktree.path, worktree.base_branch, task.title)
            task.git_changed_files = diff.changed_files
            task.git_diff = diff.diff_text
        except git_worktree.WorktreeError as exc:
            # Never overturn the adapter's own real success/failure verdict
            # over a diff-collection problem -- just note it honestly.
            note = f"Task output recorded, but could not collect the git diff: {exc.detail}"
            task.error_message = f"{task.error_message} ({note})" if task.error_message else note
            diff = None

        # Phase 15: a task that actually changed files gets its branch
        # pushed and a real pull request opened from it (or, on a
        # follow-up turn, just pushed again -- GitHub reflects the new
        # commits on the same already-open PR automatically, so there's
        # nothing more to do once `task.git_pr_url` is already set) --
        # never a fabricated PR number/URL, and never overturning the
        # task's own success/failure verdict over a push/PR problem.
        if diff is not None and diff.changed_files and connection_record is not None:
            try:
                git_worktree.push_branch(worktree.path, worktree.branch_name, worktree.clone_secret)
                if not task.git_pr_url:
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
                    db.add(
                        Approval(
                            project_id=task.project_id,
                            category=ApprovalCategory.CODE_CHANGE,
                            title="Pull Request Creation",
                            subtitle=f"{task.title} (#{pr.number})",
                            priority=ApprovalPriority.HIGH,
                            task_id=task.id,
                            requested_by_user_id=task.created_by_user_id,
                        )
                    )
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
                        # Informational only -- never overturn the PR that
                        # was already opened successfully over this lookup
                        # failing.
                        note = f"Pull request opened, but could not read the base branch's protection rules: {exc.detail}"
                        task.error_message = f"{task.error_message} ({note})" if task.error_message else note
            except (git_worktree.WorktreeError, GitProviderError) as exc:
                note = f"Task output recorded, but could not open/update the pull request: {exc.detail}"
                task.error_message = f"{task.error_message} ({note})" if task.error_message else note

        # P3-1: a real test-suite run against this task's own worktree,
        # whatever framework it actually uses -- never simulated. Runs
        # last, after the PR itself is already opened/updated, so a
        # polling caller never observes a "completed" task whose PR
        # section hasn't actually finished yet (run_tests_for_task does
        # its own commit).
        try:
            test_execution.run_tests_for_task(db, task)
        except test_execution.NoWorktreeError:
            pass
    db.commit()


def execute_followup(
    db: DBSession, task: Task, instruction: str, extra_should_cancel: Callable[[], bool] | None = None
) -> None:
    """Runs a real follow-up turn: resumes the task's existing Git worktree
    (its earlier changes are still there on disk) and re-invokes the same
    coding-agent connection with the new instruction plus the real prior
    conversation as context -- never a fresh, context-free execution dressed
    up as a continuation. Requires the task to have already run once with a
    real repository connection (i.e. `task.git_branch_name` is set); a task
    that never had a worktree (no repo connected, or its first run failed
    before a worktree existed) has nothing to resume, and fails honestly
    rather than silently falling back to a stateless run."""
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
        fail("This task has no existing workspace to continue in — start it at least once first.")
        return
    if task.coding_agent_connection_id is None:
        fail("No coding-agent connection assigned to this task.")
        return

    connection = db.get(CodingAgentConnection, task.coding_agent_connection_id)
    adapter = get_adapter(connection.runtime_slug) if connection else None
    if connection is None or adapter is None:
        fail("Assigned coding-agent connection no longer exists.")
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
        fail(f"Could not resume this task's Git workspace: {exc.detail}")
        return

    # A multi-paragraph prompt that labels the instruction as separate
    # "context" genuinely confuses this CLI agent in practice -- it either
    # refuses the Write tool outright or fixates on the task's original
    # (often now-irrelevant) title instead of the real instruction. A
    # single flowing sentence that states the continuation and the
    # instruction together is what actually gets real file edits made;
    # this was verified empirically, not assumed. The real conversation
    # history still exists and is shown in the UI (see the `/messages`
    # route) -- it's just not fed back into this CLI invocation, which has
    # no native session memory of its own anyway (each run is a fresh
    # process).
    prompt = (
        "This repository checkout already has the real changes from earlier turns of this "
        f"task -- continue in it, don't start over. {instruction}"
    )

    _run_adapter_and_finish(
        db, task, adapter, credential_value, prompt, worktree, connection_record, extra_should_cancel,
        agent_connection=connection,
    )
    if task.status == TaskStatus.COMPLETED:
        db.add(TaskMessage(task_id=task.id, role=TaskMessageRole.AGENT, content=task.output or ""))
        db.commit()
    else:
        db.add(
            TaskMessage(
                task_id=task.id,
                role=TaskMessageRole.SYSTEM,
                content=task.error_message or "The follow-up run failed.",
            )
        )
        db.commit()


def start_followup_in_background(task_id: uuid.UUID, instruction: str) -> None:
    thread = threading.Thread(target=_run_followup, args=(task_id, instruction), daemon=True)
    thread.start()


def _run_followup(task_id: uuid.UUID, instruction: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        execute_followup(db, task, instruction)
    finally:
        db.close()


def _run(task_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        if task is None:
            return
        execute_task(db, task)
    finally:
        db.close()

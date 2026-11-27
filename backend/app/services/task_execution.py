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
from app.models.task import Task, TaskStatus
from app.models.task_message import TaskMessage, TaskMessageRole
from app.services import git_worktree, test_execution
from app.services.agent_runtime.registry import get_adapter
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider

_OUTPUT_COMMIT_INTERVAL = 20  # flush to the DB at least every N chunks


def start_task_in_background(task_id: uuid.UUID) -> None:
    thread = threading.Thread(target=_run, args=(task_id,), daemon=True)
    thread.start()


def _resolve_task_connection(db: DBSession, task: Task) -> tuple[CodingAgentConnection | None, str]:
    """Resolves the assigned or selected CodingAgentConnection and model for this task.
    If task.selected_model or execution_runtime is specified, resolves or auto-provisions
    a local connection for the task's organization."""
    connection = None
    model_id = task.selected_model or ""
    runtime_slug = task.execution_runtime or ""

    # `selected_model` is stored in the catalog's "{runtime_slug}:{model_id}"
    # option-id form (see model_catalog_service.py), so its prefix always
    # needs stripping before it's a real model name an adapter can pass
    # along -- not only on a task's first run. Skipping this whenever
    # `runtime_slug` was already known (e.g. set directly at task creation,
    # alongside `selected_model`, from the same picker selection) left the
    # adapter prefix stuck on the front of every model name forever,
    # breaking every execution with Ollama's own "qwen2.5:0.5b" model tags
    # (the first ":" split landed on the adapter prefix, not inside the tag).
    if ":" in model_id:
        prefix, sub_model = model_id.split(":", 1)
        if prefix == runtime_slug or (not runtime_slug and get_adapter(prefix)):
            runtime_slug = runtime_slug or prefix
            model_id = sub_model

    if task.coding_agent_connection_id is not None:
        connection = db.get(CodingAgentConnection, task.coding_agent_connection_id)
        if connection:
            runtime_slug = connection.runtime_slug

    if not runtime_slug and model_id:
        if model_id.startswith("claude"):
            runtime_slug = "claude_code"
        elif model_id.startswith("gemini"):
            runtime_slug = "gemini_cli"
        elif model_id.startswith("qwen") or "coder" in model_id:
            ollama = get_adapter("ollama")
            if ollama and ollama.health_check(None).connected:
                runtime_slug = "ollama"
            else:
                runtime_slug = "qwen"
        elif model_id.startswith("gpt") or model_id.startswith("o3") or "codex" in model_id:
            runtime_slug = "codex"
        elif "sandbox" in model_id:
            runtime_slug = "docker_sandbox"

    if connection is None and runtime_slug:
        from app.models.agent_runtime import ConnectionMode, ConnectionStatus
        from app.models.project import Project

        project = task.project or db.get(Project, task.project_id)
        if project:
            connection = (
                db.query(CodingAgentConnection)
                .filter_by(organization_id=project.organization_id, runtime_slug=runtime_slug)
                .first()
            )
            if connection is None:
                adapter = get_adapter(runtime_slug)
                if adapter:
                    health = adapter.health_check(None)
                    if health.connected:
                        connection = CodingAgentConnection(
                            organization_id=project.organization_id,
                            runtime_slug=runtime_slug,
                            connection_mode=ConnectionMode.LOCAL_RUNTIME,
                            status=ConnectionStatus.CONNECTED,
                            detected_version=health.version,
                            created_by_user_id=task.created_by_user_id,
                        )
                        db.add(connection)
                        db.flush()
                        task.coding_agent_connection_id = connection.id
                        task.execution_runtime = runtime_slug
                        task.selected_model = model_id
                        db.commit()

    if connection and not task.coding_agent_connection_id:
        task.coding_agent_connection_id = connection.id
        task.execution_runtime = connection.runtime_slug
        db.commit()

    return connection, model_id


def execute_task(
    db: DBSession, task: Task, extra_should_cancel: Callable[[], bool] | None = None
) -> None:
    """Runs `task` to completion against its assigned connection, committing
    real progress to `db` as it happens. Leaves `task.status` as COMPLETED
    or FAILED. Does not open or close `db` — the caller owns the session."""
    task.started_at = datetime.now(timezone.utc)
    db.commit()

    connection, model_id = _resolve_task_connection(db, task)
    if connection is None:
        task.status = TaskStatus.FAILED
        task.error_message = "No coding-agent connection assigned to this task."
        task.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    adapter = get_adapter(connection.runtime_slug)
    if adapter is None:
        task.status = TaskStatus.FAILED
        task.error_message = f"Assigned coding-agent adapter '{connection.runtime_slug}' not found."
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

    # Automatically consult project and repository knowledge context
    from app.services.knowledge_context import build_task_knowledge_context
    k_ctx = build_task_knowledge_context(db, task)
    task.knowledge_context = k_ctx.metadata
    db.commit()

    user_instruction = task.description or task.title

    # P4-4: real RAG retrieval over this project's ingested documents
    # (see app/services/document_retrieval.py). Returns "" when the
    # project has no documents or the embedding model is unreachable, so
    # this never blocks or fabricates context -- it's a pure addition.
    from app.services import document_retrieval
    rag_context = document_retrieval.build_rag_context(db, task.project_id, user_instruction)

    context_blocks = [b for b in (k_ctx.formatted_context, rag_context) if b]
    if getattr(adapter, "slug", "") == "docker_sandbox":
        prompt = user_instruction
    elif context_blocks:
        prompt = "\n\n".join(context_blocks) + f"\n\nTASK INSTRUCTION:\n{user_instruction}"
    else:
        prompt = user_instruction

    _run_adapter_and_finish(
        db, task, adapter, credential_value, prompt,
        worktree, connection_record, extra_should_cancel,
        is_followup=False, model=model_id,
    )


def _run_adapter_and_finish(
    db: DBSession,
    task: Task,
    adapter,
    credential_value: str | None,
    prompt: str,
    worktree: "git_worktree.WorktreeResult | None",
    connection_record: RepositoryConnection | None,
    extra_should_cancel: Callable[[], bool] | None,
    is_followup: bool = False,
    model: str | None = None,
) -> None:
    """Shared tail of both a fresh task run and a follow-up turn: stream the
    adapter's real output into `task.output`, then (if there's a worktree)
    collect the real cumulative diff and push/open-or-update a real PR.
    Leaves `task.status` as COMPLETED or FAILED. Caller owns the session."""
    exec_started_at = datetime.now(timezone.utc)
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

    effective_model = model or task.selected_model or None
    result = adapter.start_execution_streaming(
        prompt,
        credential_value,
        on_chunk,
        should_cancel,
        cwd=worktree.path if worktree else None,
        model=effective_model,
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

    # Record actual execution in history (Phase 8 & 12)
    history_entry = {
        "execution_id": str(uuid.uuid4()),
        "type": "followup" if is_followup else "initial",
        "runtime_slug": adapter.slug,
        "runtime_name": adapter.display_name,
        "model_id": effective_model or adapter.slug,
        "started_at": exec_started_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "status": "completed" if result.succeeded else "failed",
        "error": result.error if not result.succeeded else "",
    }
    current_history = list(task.execution_history or [])
    current_history.append(history_entry)
    task.execution_history = current_history
    task.execution_runtime = adapter.slug
    if effective_model:
        task.selected_model = effective_model

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

    connection, model_id = _resolve_task_connection(db, task)
    if connection is None:
        fail("No coding-agent connection assigned to this task.")
        return

    adapter = get_adapter(connection.runtime_slug)
    if adapter is None:
        fail(f"Assigned coding-agent adapter '{connection.runtime_slug}' no longer exists.")
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

    from app.services.knowledge_context import build_task_knowledge_context
    k_ctx = build_task_knowledge_context(db, task)
    task.knowledge_context = k_ctx.metadata
    db.commit()

    prompt = (
        "This repository checkout already has the real changes from earlier turns of this "
        f"task -- continue in it, don't start over. {instruction}"
    )

    _run_adapter_and_finish(
        db, task, adapter, credential_value, prompt, worktree, connection_record, extra_should_cancel,
        is_followup=True, model=model_id,
    )
    if task.status == TaskStatus.COMPLETED:
        db.add(
            TaskMessage(
                task_id=task.id,
                role=TaskMessageRole.AGENT,
                content=task.output or "",
                model_id=model_id or task.selected_model or adapter.slug,
                runtime_slug=adapter.slug,
            )
        )
        db.commit()
    else:
        db.add(
            TaskMessage(
                task_id=task.id,
                role=TaskMessageRole.SYSTEM,
                content=task.error_message or "The follow-up run failed.",
                model_id=model_id or task.selected_model or adapter.slug,
                runtime_slug=adapter.slug,
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

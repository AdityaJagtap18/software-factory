"""The Factory Supervisor (Phase 5, P5-1): runs a workflow's steps against
real dependency-aware scheduling, real capability-based agent assignment,
and real retry-with-fallback -- while remaining exactly backward compatible
with the original "ordered list of Task rows, run one after another,
halt on the first real failure" model for any workflow that doesn't opt
into the new fields (`required_capability`, `depends_on_step_orders`,
`max_retries` all default to empty/zero).

Scheduling model: steps run in rounds. A step becomes "ready" once every
step ID in its dependency set has genuinely `completed` (never partially,
never "probably"). A step with no explicit `depends_on_step_orders` and
no steps having already been skipped) is the ONLY code path that ever
diverges from one-step-at-a-time -- and even then, only for workflows that
explicitly declare a smaller dependency set than "everything before me".

Within one round, every ready step actually runs concurrently in its own
thread and its own DB session (SQLAlchemy sessions are not thread-safe,
so sharing one across threads would be a real correctness bug, not just a
style issue) -- this is the real "parallel execution where safe" the
roadmap asks for, not a cosmetic reordering. Once a step starts, it is
allowed to finish even if a sibling in the same round fails (there is no
way to abort an in-flight CLI/API call other than the existing
`cancel_requested` check at its next chunk boundary) -- but no NEW round
ever starts once any step in the current round has genuinely failed and
exhausted its retries. A workflow only ever reaches COMPLETED once every
one of its steps has genuinely completed.
"""

import threading
import uuid
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.workflow import Workflow, WorkflowStatus
from app.services import agent_assignment, handoff as handoff_service
from app.services.task_execution import execute_task

_CONTEXT_EXCERPT_CHARS = 2_000


def start_workflow_in_background(workflow_id: uuid.UUID) -> None:
    thread = threading.Thread(target=_run_workflow, args=(workflow_id,), daemon=True)
    thread.start()


def _dependency_set(step: Task, all_orders: list[int]) -> set[int]:
    """Explicit deps (even an explicit empty set, meaning "none") if the
    step declared any at all (`depends_on_step_orders is not None`);
    otherwise every prior step (the original, exactly-sequential default)
    -- see module docstring."""
    if step.depends_on_step_orders is not None:
        return set(step.depends_on_step_orders)
    return {o for o in all_orders if o < step.step_order}


def _cancel_requested(workflow_id: uuid.UUID) -> bool:
    db = SessionLocal()
    try:
        workflow = db.get(Workflow, workflow_id)
        return bool(workflow and workflow.cancel_requested)
    finally:
        db.close()


def _apply_shared_context(task: Task, deps: set[int], shared_context: dict) -> None:
    """P5-1: real "shared workflow state" -- a step that EXPLICITLY
    declares a dependency on an earlier step gets that earlier step's real
    output folded into its own prompt, so it is working from genuine
    upstream results rather than just trusting the shared worktree on
    disk. Deliberately opt-in (`task.depends_on_step_orders is not None`):
    a workflow that never declares any dependency gets the exact same step
    prompts as before this feature existed -- no implicit context
    injection for the default-sequential case."""
    if task.depends_on_step_orders is None:
        return
    lines = []
    for dep_order in sorted(deps):
        info = shared_context.get(str(dep_order))
        if info:
            lines.append(f"- Step {dep_order} ({info['title']}): {info['output_excerpt']}")
    if lines:
        note = "Context from prior workflow steps this one depends on:\n" + "\n".join(lines)
        task.description = f"{task.description}\n\n{note}".strip() if task.description else note


def _assign_connection_for_step(db, task: Task, organization_id: uuid.UUID) -> str | None:
    """P5-1: capability-based auto-assignment. Returns an honest
    escalation error message if nothing eligible exists -- never assigns a
    connection it didn't actually find, and never starts a doomed
    execution. No-op (returns None) when the step already has a connection
    or declares no required capability, preserving the original
    human-assigned-connection behavior exactly."""
    if task.coding_agent_connection_id is not None or not task.required_capability:
        return None
    connection = agent_assignment.select_connection(db, organization_id, task.required_capability)
    if connection is None:
        return (
            f"No eligible, connected agent found for required capability "
            f"'{task.required_capability}' — escalating (task left unassigned)."
        )
    task.coding_agent_connection_id = connection.id
    db.commit()
    return None


def _run_step_with_retry(
    task_id: uuid.UUID,
    workflow_id: uuid.UUID,
    organization_id: uuid.UUID,
    deps: set[int],
    shared_context: dict,
) -> bool:
    """Runs one step to a terminal state in its OWN session/thread,
    including capability assignment and retry-with-fallback. Returns True
    iff the step ends COMPLETED."""
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        workflow = db.get(Workflow, workflow_id)

        _apply_shared_context(task, deps, shared_context)
        escalation_error = _assign_connection_for_step(db, task, organization_id)
        if escalation_error:
            task.status = TaskStatus.FAILED
            task.error_message = escalation_error
            task.started_at = datetime.now(timezone.utc)
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
            return False

        task.status = TaskStatus.RUNNING
        task.cancel_requested = False
        task.output = ""
        task.error_message = ""
        task.completed_at = None
        db.commit()

        def extra_should_cancel() -> bool:
            return _cancel_requested(workflow_id)

        execute_task(db, task, extra_should_cancel=extra_should_cancel)

        while task.status != TaskStatus.COMPLETED and task.retry_count < task.max_retries:
            failed_connection_id = task.coding_agent_connection_id
            fallback = agent_assignment.select_connection(
                db,
                organization_id,
                task.required_capability,
                exclude_connection_ids={failed_connection_id} if failed_connection_id else None,
            )
            if fallback is None:
                break  # no other provider to fall back to -- fail honestly, don't loop forever

            task.retry_count += 1
            db.commit()
            new_handoff = handoff_service.create_handoff(
                db,
                task,
                fallback.id,
                reason=f"Automatic retry {task.retry_count}/{task.max_retries} after: {task.error_message}",
                automatic=True,
            )
            handoff_service.resume_task_with_handoff(db, task, new_handoff)

        return task.status == TaskStatus.COMPLETED
    finally:
        db.close()


def _run_workflow(workflow_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        workflow = db.get(Workflow, workflow_id)
        if workflow is None:
            return
        project = db.get(Project, workflow.project_id)
        organization_id = project.organization_id

        steps = (
            db.query(Task).filter_by(workflow_id=workflow_id).order_by(Task.step_order).all()
        )
        all_orders = [s.step_order for s in steps]
        by_order = {s.step_order: s for s in steps}

        workflow.started_at = datetime.now(timezone.utc)
        db.commit()

        if workflow.cancel_requested:
            for step in steps:
                step.status = TaskStatus.FAILED
                step.error_message = "Workflow cancelled before this step started."
            db.commit()
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        succeeded: set[int] = set()
        failed_or_skipped: set[int] = set()
        shared_context: dict = dict(workflow.shared_context or {})
        halted = False

        remaining = list(steps)
        while remaining and not halted:
            ready = [
                s
                for s in remaining
                if _dependency_set(s, all_orders) <= succeeded
            ]
            if not ready:
                # Every remaining step depends on something that failed/
                # never ran -- leave them exactly as they are
                # (NOT_STARTED), matching the original halt-on-failure
                # behavior for the default sequential case.
                break

            for s in ready:
                remaining.remove(s)
            db.refresh(workflow, attribute_names=["cancel_requested"])
            if workflow.cancel_requested:
                for s in ready:
                    s.status = TaskStatus.FAILED
                    s.error_message = "Workflow cancelled before this step started."
                db.commit()
                halted = True
                break

            workflow.current_step_index = min(s.step_order for s in ready)
            db.commit()

            results: dict[int, bool] = {}
            if len(ready) == 1:
                step = ready[0]
                results[step.step_order] = _run_step_with_retry(
                    step.id, workflow_id, organization_id, _dependency_set(step, all_orders), shared_context
                )
            else:
                threads = []
                lock_results = threading.Lock()

                def _worker(step: Task) -> None:
                    ok = _run_step_with_retry(
                        step.id,
                        workflow_id,
                        organization_id,
                        _dependency_set(step, all_orders),
                        shared_context,
                    )
                    with lock_results:
                        results[step.step_order] = ok

                for s in ready:
                    t = threading.Thread(target=_worker, args=(s,), daemon=True)
                    threads.append(t)
                    t.start()
                for t in threads:
                    t.join()

            any_failed = False
            for s in ready:
                db.refresh(s)
                if results.get(s.step_order):
                    succeeded.add(s.step_order)
                    shared_context[str(s.step_order)] = {
                        "title": s.title,
                        "status": "completed",
                        "output_excerpt": (s.output or "")[:_CONTEXT_EXCERPT_CHARS],
                        "git_changed_files": list(s.git_changed_files or []),
                    }
                else:
                    failed_or_skipped.add(s.step_order)
                    any_failed = True

            workflow.shared_context = shared_context
            db.commit()

            if any_failed:
                halted = True

        if halted or failed_or_skipped or remaining:
            workflow.status = WorkflowStatus.FAILED
        else:
            workflow.status = WorkflowStatus.COMPLETED
            workflow.current_step_index = len(steps)
        workflow.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

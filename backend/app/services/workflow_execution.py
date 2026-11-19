"""The Factory Supervisor: runs a workflow's ordered steps (Task rows)
sequentially in a single background thread, reusing the exact same
per-task execution pipeline as a standalone task start.

Non-negotiable: a workflow is only ever marked `completed` once every one
of its steps has genuinely `completed`. The first step that really fails
halts the workflow immediately — it is marked `failed` and no later step
is ever started, let alone fabricated as succeeded. A workflow-level
cancel is honored before the next step starts, and also interrupts the
currently-running step at its next real chunk boundary, exactly like a
single task's cancel.
"""

import threading
import uuid
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.task import Task, TaskStatus
from app.models.workflow import Workflow, WorkflowStatus
from app.services.task_execution import execute_task


def start_workflow_in_background(workflow_id: uuid.UUID) -> None:
    thread = threading.Thread(target=_run_workflow, args=(workflow_id,), daemon=True)
    thread.start()


def _run_workflow(workflow_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        workflow = db.get(Workflow, workflow_id)
        if workflow is None:
            return

        steps = (
            db.query(Task)
            .filter_by(workflow_id=workflow_id)
            .order_by(Task.step_order)
            .all()
        )

        workflow.started_at = datetime.now(timezone.utc)
        db.commit()

        for index, task in enumerate(steps):
            db.refresh(workflow, attribute_names=["cancel_requested"])
            if workflow.cancel_requested:
                task.status = TaskStatus.FAILED
                task.error_message = "Workflow cancelled before this step started."
                db.commit()
                workflow.status = WorkflowStatus.FAILED
                workflow.completed_at = datetime.now(timezone.utc)
                db.commit()
                return

            workflow.current_step_index = index
            task.status = TaskStatus.RUNNING
            task.cancel_requested = False
            task.output = ""
            task.error_message = ""
            task.completed_at = None
            db.commit()

            def extra_should_cancel() -> bool:
                db.refresh(workflow, attribute_names=["cancel_requested"])
                return workflow.cancel_requested

            execute_task(db, task, extra_should_cancel=extra_should_cancel)

            if task.status != TaskStatus.COMPLETED:
                workflow.status = WorkflowStatus.FAILED
                workflow.completed_at = datetime.now(timezone.utc)
                db.commit()
                return

        workflow.status = WorkflowStatus.COMPLETED
        workflow.current_step_index = len(steps)
        workflow.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

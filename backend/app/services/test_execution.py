"""Wires real test execution (P3-1) to a task's already-cloned worktree on
disk -- reuses whatever the task's own run already checked out, never a
fresh clone just to run tests."""

import uuid

from sqlalchemy.orm import Session as DBSession

from app.models.task import Task
from app.models.test_run import TestFramework, TestRun
from app.services import git_worktree, test_runner


class NoWorktreeError(Exception):
    pass


def run_tests_for_task(db: DBSession, task: Task) -> TestRun:
    """Runs the real, detected test suite in this task's existing worktree
    and persists a real `TestRun` row. Raises `NoWorktreeError` if the task
    never had a worktree (no repository connection, or it never started)
    -- never fabricates a result for a checkout that doesn't exist."""
    worktree_path = git_worktree._worktree_root() / str(task.id)
    if not worktree_path.exists():
        raise NoWorktreeError("This task has no worktree to run tests in.")

    result = test_runner.run_tests(str(worktree_path))
    run = TestRun(
        project_id=task.project_id,
        task_id=task.id,
        framework=TestFramework(result.framework),
        ran=result.ran,
        passed=result.passed,
        failed=result.failed,
        total=result.total,
        output=result.output,
        error=result.error,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def start_test_run_in_background(task_id: uuid.UUID) -> None:
    import threading

    from app.core.database import SessionLocal

    def _run() -> None:
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            if task is None:
                return
            try:
                run_tests_for_task(db, task)
            except NoWorktreeError:
                pass
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()

"""Starts a task against a coding-agent connection.

Non-negotiable: a task is only ever marked `completed` when the adapter's
`start_execution` actually returned `succeeded=True` from a real CLI
invocation or a real provider API call. Every other path — no connection
assigned, connection not currently connected, adapter failure — marks the
task `failed` with the real error, never a fabricated success.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession

from app.core.crypto import decrypt_value
from app.models.agent_runtime import CodingAgentConnection, Credential
from app.models.task import Task, TaskStatus
from app.services.agent_runtime.registry import get_adapter


def run_task(db: DBSession, task: Task) -> Task:
    task.started_at = datetime.now(timezone.utc)

    if task.coding_agent_connection_id is None:
        task.status = TaskStatus.FAILED
        task.error_message = "No coding-agent connection assigned to this task."
        task.completed_at = datetime.now(timezone.utc)
        return task

    connection = db.get(CodingAgentConnection, task.coding_agent_connection_id)
    adapter = get_adapter(connection.runtime_slug) if connection else None
    if connection is None or adapter is None:
        task.status = TaskStatus.FAILED
        task.error_message = "Assigned coding-agent connection no longer exists."
        task.completed_at = datetime.now(timezone.utc)
        return task

    credential_value = None
    if connection.credential_id is not None:
        credential = db.get(Credential, connection.credential_id)
        if credential is not None:
            credential_value = decrypt_value(credential.encrypted_value)

    # Re-check connectivity right before running — a cached "connected"
    # status from an earlier health check could be stale (CLI uninstalled
    # since, key revoked since). Never start work on a stale assumption.
    health = adapter.health_check(credential_value)
    if not health.connected:
        task.status = TaskStatus.FAILED
        task.error_message = f"{adapter.display_name} is not connected: {health.detail}"
        task.completed_at = datetime.now(timezone.utc)
        return task

    result = adapter.start_execution(task.description or task.title, credential_value)
    task.completed_at = datetime.now(timezone.utc)
    if result.succeeded:
        task.status = TaskStatus.COMPLETED
        task.output = result.output
        task.error_message = ""
    else:
        task.status = TaskStatus.FAILED
        task.error_message = result.error
    return task

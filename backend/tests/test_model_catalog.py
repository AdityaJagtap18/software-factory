"""Tests for ChatGPT-style Model Catalog, Local Model Discovery, and Execution Routing."""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.models.agent_runtime import CodingAgentConnection, ConnectionMode, ConnectionStatus
from app.models.task import Task, TaskPriority, TaskStatus
from app.services.agent_runtime.registry import all_adapters, get_adapter
from app.services.model_catalog_service import get_model_catalog


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "full_name": name, "password": "password123"},
    )
    res = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _project(client, headers, name="Acme"):
    org = client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Alpha", "description": "Desc"},
        headers=headers,
    ).json()
    return org, project


def test_registry_contains_adapters_with_models():
    """All required coding-agent adapters exist and declare models."""
    slugs = [a.slug for a in all_adapters()]
    assert "claude_code" in slugs
    assert "gemini_cli" in slugs
    assert "codex" in slugs
    assert "ollama" in slugs
    assert "qwen" in slugs
    assert "docker_sandbox" in slugs
    assert "custom" in slugs

    claude = get_adapter("claude_code")
    assert "claude-3-7-sonnet" in claude.supported_models()

    gemini = get_adapter("gemini_cli")
    assert "gemini-2.5-pro" in gemini.supported_models()

    ollama = get_adapter("ollama")
    assert len(ollama.supported_models()) > 0


def test_model_catalog_groups_and_availability(client):
    """Model catalog groups models by provider and reflects honest availability."""
    from app.core.database import SessionLocal
    alice = _register_and_login(client, "alice_catalog@example.com", "Alice")
    org, project = _project(client, alice)

    db = SessionLocal()
    try:
        catalog = get_model_catalog(db, uuid.UUID(org["id"]))
        assert len(catalog.groups) >= 3
        assert len(catalog.models) > 0

        group_names = [g.provider_name for g in catalog.groups]
        assert "Anthropic" in group_names
        assert "Google" in group_names
        assert "OpenAI" in group_names

        # Anthropic models
        anthropic_group = next(g for g in catalog.groups if g.provider_name == "Anthropic")
        anthropic_model_ids = [m.model_id for m in anthropic_group.models]
        assert "claude-3-7-sonnet" in anthropic_model_ids
        assert "claude-3-5-sonnet" in anthropic_model_ids

        # Every model has required fields
        for m in catalog.models:
            assert m.id
            assert m.provider_id
            assert m.provider_name
            assert m.model_id
            assert m.model_name
            assert m.display_name
            assert m.runtime_slug
            assert m.availability_status in [
                "CONNECTED", "AVAILABLE", "DISCONNECTED", "UNAVAILABLE", "MISCONFIGURED", "ERROR"
            ]
    finally:
        db.close()


def test_model_catalog_api_endpoint(client):
    """GET /projects/{project_id}/agent-runtimes/model-catalog returns 200 with catalog response."""
    alice = _register_and_login(client, "alice_cat2@example.com", "Alice")
    org, project = _project(client, alice)

    res = client.get(
        f"/api/v1/projects/{project['id']}/agent-runtimes/model-catalog",
        headers=alice,
    )
    assert res.status_code == 200
    data = res.json()
    assert "groups" in data
    assert "models" in data
    assert "default_model_id" in data
    assert len(data["groups"]) > 0
    assert len(data["models"]) > 0


def test_task_creation_with_selected_model(client):
    """Task creation persists selected_model and execution_runtime."""
    alice = _register_and_login(client, "alice_task_create@example.com", "Alice")
    org, project = _project(client, alice)

    res = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        headers=alice,
        json={
            "title": "Refactor auth handler",
            "description": "Implement token validation",
            "priority": "high",
            "selected_model": "claude-3-7-sonnet",
            "execution_runtime": "claude_code",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Refactor auth handler"
    assert data["selected_model"] == "claude-3-7-sonnet"
    assert data["execution_runtime"] == "claude_code"
    assert "execution_history" in data
    assert isinstance(data["execution_history"], list)


def test_task_update_model_selection(client):
    """Updating a task changes its selected model without deleting state."""
    alice = _register_and_login(client, "alice_patch@example.com", "Alice")
    org, project = _project(client, alice)

    create_res = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        headers=alice,
        json={
            "title": "Initial Task",
            "selected_model": "claude-3-5-sonnet",
            "execution_runtime": "claude_code",
        },
    )
    task_id = create_res.json()["id"]

    # Patch model
    res = client.patch(
        f"/api/v1/projects/{project['id']}/tasks/{task_id}",
        headers=alice,
        json={
            "selected_model": "gemini-2.5-pro",
            "execution_runtime": "gemini_cli",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["selected_model"] == "gemini-2.5-pro"
    assert data["execution_runtime"] == "gemini_cli"


def test_task_message_records_model_provenance(client, monkeypatch):
    """Follow-up message records model_id and updates selection."""
    from app.services.agent_runtime.adapters import ClaudeCodeAdapter
    from app.services.agent_runtime.base import ExecutionResult

    alice = _register_and_login(client, "alice_conv@example.com", "Alice")
    org, project = _project(client, alice)

    # Stub execution edge
    def fake_streaming(self, prompt, credential_value, on_chunk, should_cancel, cwd=None, model=None):
        on_chunk("fake response")
        return ExecutionResult(succeeded=True, output="fake response")

    monkeypatch.setattr(ClaudeCodeAdapter, "start_execution_streaming", fake_streaming)

    # Create task via client
    create_res = client.post(
        f"/api/v1/projects/{project['id']}/tasks",
        headers=alice,
        json={
            "title": "Conversation Task",
            "selected_model": "claude-3-7-sonnet",
            "execution_runtime": "claude_code",
        },
    )
    task_id = create_res.json()["id"]

    # Give it a branch so follow-up can run
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        t = db.get(Task, uuid.UUID(task_id))
        t.status = TaskStatus.COMPLETED
        t.git_branch_name = "sf/task-test-conv"
        db.commit()
    finally:
        db.close()

    # Send message with updated model
    res = client.post(
        f"/api/v1/projects/{project['id']}/tasks/{task_id}/messages",
        headers=alice,
        json={
            "content": "Add unit tests for the changes",
            "selected_model": "gemini-2.5-pro",
        },
    )
    assert res.status_code == 201
    msg_data = res.json()
    assert msg_data["content"] == "Add unit tests for the changes"
    assert msg_data["model_id"] == "gemini-2.5-pro"

    # Verify task was updated
    db = SessionLocal()
    try:
        t = db.get(Task, uuid.UUID(task_id))
        assert t.selected_model == "gemini-2.5-pro"
    finally:
        db.close()

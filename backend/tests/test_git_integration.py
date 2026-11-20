"""Phase 13 -- Git Connectivity & Synchronization.

These tests exercise the real mechanisms this phase adds: JWT signing and
HMAC webhook-signature verification are genuinely executed (no network
needed for either), the honest not-configured path is a real,
non-mocked call through the actual backend (this machine has no GitHub
App credentials configured, exactly like Phase 2's CLI-less adapters),
and the "GitHub actually responded" paths are exercised by monkeypatching
only the network edge (`GitHubAppAdapter` methods), never the
connected/not-connected decision logic itself -- the same convention
`test_agent_runtimes.py` uses.
"""

import hashlib
import hmac
import json

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.services import git_webhook
from app.services.git_provider import github_app
from app.services.git_provider.base import (
    BranchComparison,
    BranchComparisonCommit,
    BranchSummary,
    CommitSummary,
    CreatedRepository,
    GitProviderError,
    MergeResult,
    RepositorySummary,
)
from app.services.git_provider.github_app import GitHubAppAdapter


def _generate_test_private_key_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_TEST_PRIVATE_KEY_PEM = _generate_test_private_key_pem()


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": name},
    )
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _org_and_project(client, headers, org_name="Acme"):
    org = client.post("/api/v1/organizations", json={"name": org_name}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": "FINTRIX"}, headers=headers
    ).json()
    return org, project


# ---------------------------------------------------------------------------
# Real, non-mocked mechanism tests: JWT signing and signature verification.
# ---------------------------------------------------------------------------


def test_app_jwt_is_a_genuine_rs256_token_verifiable_with_the_matching_public_key(monkeypatch):
    """No network call -- this generates a real throwaway RSA keypair and
    confirms `_build_app_jwt` produces a token that a real RS256 verifier
    (using only the public half) actually accepts, with the claims GitHub's
    App auth spec requires."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    fake_settings = Settings(github_app_id="123456", github_app_private_key=private_pem)
    monkeypatch.setattr(github_app, "get_settings", lambda: fake_settings)

    token = github_app._build_app_jwt()
    decoded = pyjwt.decode(token, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == "123456"
    assert decoded["exp"] > decoded["iat"]

    # A tampered token must genuinely fail verification -- not just by convention.
    with pytest.raises(pyjwt.PyJWTError):
        pyjwt.decode(token + "x", public_pem, algorithms=["RS256"])


def test_webhook_signature_verification_is_a_real_hmac_check():
    secret = "my-real-test-secret"
    body = b'{"zen": "non-blocking is better than blocking."}'
    real_signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert git_webhook.verify_signature(secret, body, real_signature) is True
    assert git_webhook.verify_signature(secret, body, "sha256=" + "0" * 64) is False
    assert git_webhook.verify_signature(secret, body + b"tampered", real_signature) is False
    assert git_webhook.verify_signature("wrong-secret", body, real_signature) is False
    assert git_webhook.verify_signature(secret, body, None) is False
    assert git_webhook.verify_signature("", body, real_signature) is False


# ---------------------------------------------------------------------------
# Honest failure path: no GitHub App configured on this machine.
# ---------------------------------------------------------------------------


def test_installation_honestly_reports_not_connected_when_no_github_app_configured(client, monkeypatch):
    """With no SF_GITHUB_APP_ID / SF_GITHUB_APP_PRIVATE_KEY configured, a real
    (non-mocked) health check must honestly report not_connected -- never a
    simulated success. Isolated from this machine's own .env (which may have
    a real GitHub App configured for live testing) via monkeypatch, exactly
    like `test_app_jwt_is_a_genuine_rs256_token...` isolates its own keypair."""
    monkeypatch.setattr(github_app, "get_settings", lambda: Settings(github_app_id="", github_app_private_key=""))

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, _project = _org_and_project(client, alice)

    r = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "99999", "account_login": "acme-corp"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "not_connected"
    assert "not configured" in body["last_error"].lower()


def test_repository_discovery_fails_honestly_without_a_configured_app(client, monkeypatch):
    monkeypatch.setattr(github_app, "get_settings", lambda: Settings(github_app_id="", github_app_private_key=""))

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, _project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "99999"},
        headers=alice,
    ).json()

    r = client.get(
        f"/api/v1/organizations/{org['id']}/git-installations/{installation['id']}/repositories",
        headers=alice,
    )
    assert r.status_code == 502
    assert "not configured" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# RBAC and authorization.
# ---------------------------------------------------------------------------


def test_non_admin_cannot_create_installation(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org, _project = _org_and_project(client, alice)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )

    r = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=bob,
    )
    assert r.status_code == 403


def test_cross_org_installation_is_not_visible_or_usable(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org_a, _ = _org_and_project(client, alice, "Acme")
    org_b, project_b = _org_and_project(client, bob, "Globex")

    installation_a = client.post(
        f"/api/v1/organizations/{org_a['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()

    # Bob cannot see Alice's org's installations at all.
    r = client.get(f"/api/v1/organizations/{org_a['id']}/git-installations", headers=bob)
    assert r.status_code == 403

    # And cannot connect a repository using an installation from another org.
    r2 = client.post(
        f"/api/v1/projects/{project_b['id']}/repository-connections",
        json={"git_installation_id": installation_a["id"], "owner": "acme", "name": "widgets"},
        headers=bob,
    )
    assert r2.status_code == 404


def test_non_project_admin_cannot_connect_a_repository(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    bob = _register_and_login(client, "bob@example.com", "Bob")
    org, project = _org_and_project(client, alice)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "bob@example.com", "role": "member"},
        headers=alice,
    )
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "bob@example.com", "role": "developer"},
        headers=alice,
    )
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=bob,
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Repository connection creation + manual sync (success path via a stubbed
# network edge, like test_agent_runtimes.py's factory_managed tests).
# ---------------------------------------------------------------------------


def test_connecting_a_repository_syncs_real_metadata(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123", message="Initial commit"),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["default_branch"] == "main"
    assert body["last_observed_commit_sha"] == "abc123"

    r2 = client.get(f"/api/v1/projects/{project['id']}/repository-connections", headers=alice)
    assert len(r2.json()) == 1


def test_connecting_the_same_repository_twice_conflicts(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    payload = {"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"}

    r1 = client.post(f"/api/v1/projects/{project['id']}/repository-connections", json=payload, headers=alice)
    assert r1.status_code == 201

    r2 = client.post(f"/api/v1/projects/{project['id']}/repository-connections", json=payload, headers=alice)
    assert r2.status_code == 409


def test_manual_sync_recovers_after_a_real_failure(client, monkeypatch):
    """Create with the network edge failing, then recover with it fixed --
    the manual sync recovery path FR-203 requires."""
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: (_ for _ in ()).throw(
            GitProviderError("GitHub rejected the repository lookup (HTTP 404)")
        ),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    ).json()
    assert created["status"] == "error"
    assert "404" in created["last_error"]

    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="def456"),
    )
    r = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections/{created['id']}/sync", headers=alice
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "connected"
    assert body["last_observed_commit_sha"] == "def456"


# ---------------------------------------------------------------------------
# Webhook receiver: signature verification, idempotency, real sync result.
# ---------------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_with_invalid_signature_is_rejected_not_processed(client, monkeypatch):
    fake_settings = Settings(github_webhook_secret="webhook-secret")
    monkeypatch.setattr(git_webhook, "get_settings", lambda: fake_settings)

    body = json.dumps({"repository": {"full_name": "acme/widgets"}, "after": "deadbeef"}).encode()
    r = client.post(
        "/api/v1/webhooks/github",
        data=body,
        headers={
            "x-hub-signature-256": "sha256=" + "0" * 64,
            "x-github-event": "push",
            "x-github-delivery": "delivery-1",
            "content-type": "application/json",
        },
    )
    assert r.status_code == 401


def test_webhook_push_updates_connected_repository_and_is_idempotent(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )

    secret = "webhook-secret"
    fake_settings = Settings(github_webhook_secret=secret)
    monkeypatch.setattr(git_webhook, "get_settings", lambda: fake_settings)

    body = json.dumps(
        {
            "repository": {"full_name": "acme/widgets"},
            "ref": "refs/heads/main",
            "after": "newcommitsha123",
        }
    ).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "push",
        "x-github-delivery": "delivery-xyz",
        "content-type": "application/json",
    }

    r1 = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r1.status_code == 200, r1.text
    assert "synced" in r1.json()["processing_result"]

    conn = client.get(f"/api/v1/projects/{project['id']}/repository-connections", headers=alice).json()[0]
    assert conn["last_observed_commit_sha"] == "newcommitsha123"
    assert conn["status"] == "connected"

    # A redelivery of the exact same delivery id must not be reprocessed.
    r2 = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]


def test_webhook_for_unknown_repository_is_recorded_not_an_error(client, monkeypatch):
    secret = "webhook-secret"
    fake_settings = Settings(github_webhook_secret=secret)
    monkeypatch.setattr(git_webhook, "get_settings", lambda: fake_settings)

    body = json.dumps({"repository": {"full_name": "nobody/nothing"}, "after": "x"}).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "push",
        "x-github-delivery": "delivery-unknown",
        "content-type": "application/json",
    }
    r = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r.status_code == 200
    assert "no matching repository connection" in r.json()["processing_result"]


def test_webhook_pull_request_event_updates_the_originating_tasks_pr_state(client, monkeypatch):
    """Phase 16: GitHub's own `pull_request` webhook is the only source of
    truth for a PR's real lifecycle -- matched purely by PR number within
    the connected project, never guessed or polled."""
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )

    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Add a feature"}, headers=alice
    ).json()

    import uuid as uuid_module

    from app.core.database import SessionLocal
    from app.models.task import Task

    db = SessionLocal()
    db_task = db.get(Task, uuid_module.UUID(task["id"]))
    db_task.git_pr_number = 42
    db_task.git_pr_state = "open"
    db.commit()
    db.close()

    secret = "webhook-secret"
    monkeypatch.setattr(git_webhook, "get_settings", lambda: Settings(github_webhook_secret=secret))

    body = json.dumps(
        {
            "action": "closed",
            "repository": {"full_name": "acme/widgets"},
            "pull_request": {"number": 42, "state": "closed", "merged": True},
        }
    ).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-pr-merged",
        "content-type": "application/json",
    }
    r = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r.status_code == 200, r.text
    assert "updated pull request state to 'merged'" in r.json()["processing_result"]

    r2 = client.get(f"/api/v1/projects/{project['id']}/tasks/{task['id']}", headers=alice)
    assert r2.json()["git_pr_state"] == "merged"


def test_webhook_pull_request_event_with_no_matching_task_is_recorded_not_an_error(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )

    secret = "webhook-secret"
    monkeypatch.setattr(git_webhook, "get_settings", lambda: Settings(github_webhook_secret=secret))
    body = json.dumps(
        {
            "repository": {"full_name": "acme/widgets"},
            "pull_request": {"number": 999, "state": "open", "merged": False},
        }
    ).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-pr-no-match",
        "content-type": "application/json",
    }
    r = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r.status_code == 200
    assert "matches no task" in r.json()["processing_result"]


def test_webhook_check_suite_event_updates_the_matching_tasks_ci_status(client, monkeypatch):
    """Phase 17: GitHub's own `check_suite` webhook is the only source of
    truth for a task's real CI result, matched by its real head branch
    within the connected project -- never run or simulated locally."""
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )

    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Add a feature"}, headers=alice
    ).json()

    import uuid as uuid_module

    from app.core.database import SessionLocal
    from app.models.task import Task

    db = SessionLocal()
    db_task = db.get(Task, uuid_module.UUID(task["id"]))
    db_task.git_branch_name = "sf-task-abc12345"
    db.commit()
    db.close()

    secret = "webhook-secret"
    monkeypatch.setattr(git_webhook, "get_settings", lambda: Settings(github_webhook_secret=secret))

    body = json.dumps(
        {
            "action": "completed",
            "repository": {"full_name": "acme/widgets"},
            "check_suite": {"head_branch": "sf-task-abc12345", "status": "completed", "conclusion": "success"},
        }
    ).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "check_suite",
        "x-github-delivery": "delivery-ci-success",
        "content-type": "application/json",
    }
    r = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r.status_code == 200, r.text
    assert "updated CI status to 'success'" in r.json()["processing_result"]

    r2 = client.get(f"/api/v1/projects/{project['id']}/tasks/{task['id']}", headers=alice)
    assert r2.json()["git_ci_status"] == "success"


def test_webhook_check_suite_in_progress_reports_its_real_status_not_a_conclusion(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )

    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Add a feature"}, headers=alice
    ).json()

    import uuid as uuid_module

    from app.core.database import SessionLocal
    from app.models.task import Task

    db = SessionLocal()
    db_task = db.get(Task, uuid_module.UUID(task["id"]))
    db_task.git_branch_name = "sf-task-def67890"
    db.commit()
    db.close()

    secret = "webhook-secret"
    monkeypatch.setattr(git_webhook, "get_settings", lambda: Settings(github_webhook_secret=secret))
    body = json.dumps(
        {
            "action": "in_progress",
            "repository": {"full_name": "acme/widgets"},
            "check_suite": {"head_branch": "sf-task-def67890", "status": "in_progress", "conclusion": None},
        }
    ).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "check_suite",
        "x-github-delivery": "delivery-ci-in-progress",
        "content-type": "application/json",
    }
    r = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r.status_code == 200
    assert "updated CI status to 'in_progress'" in r.json()["processing_result"]


def test_webhook_check_suite_with_no_matching_task_is_recorded_not_an_error(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=alice,
    )

    secret = "webhook-secret"
    monkeypatch.setattr(git_webhook, "get_settings", lambda: Settings(github_webhook_secret=secret))
    body = json.dumps(
        {
            "repository": {"full_name": "acme/widgets"},
            "check_suite": {"head_branch": "some-other-branch", "status": "completed", "conclusion": "failure"},
        }
    ).encode()
    headers = {
        "x-hub-signature-256": _sign(secret, body),
        "x-github-event": "check_suite",
        "x-github-delivery": "delivery-ci-no-match",
        "content-type": "application/json",
    }
    r = client.post("/api/v1/webhooks/github", data=body, headers=headers)
    assert r.status_code == 200
    assert "matches no task" in r.json()["processing_result"]


def test_webhook_requires_delivery_id(client):
    r = client.post(
        "/api/v1/webhooks/github",
        data=b"{}",
        headers={"x-github-event": "push", "content-type": "application/json"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Phase 15: opening a real pull request from a task's branch.
# ---------------------------------------------------------------------------


def test_create_pull_request_fails_honestly_without_a_configured_app(monkeypatch):
    monkeypatch.setattr(github_app, "get_settings", lambda: Settings(github_app_id="", github_app_private_key=""))

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().create_pull_request("1", "acme", "widgets", "feature", "main", "A title")

    assert "not configured" in exc_info.value.detail.lower()


def test_create_pull_request_sends_the_real_github_api_call_and_parses_the_response(monkeypatch):
    """The network edge (`httpx.post`) is the only thing stubbed here --
    everything else (JWT minting, request construction, response parsing)
    is the real adapter code running end to end."""
    captured = {}

    class _FakeTokenResponse:
        status_code = 201

        def json(self):
            return {"token": "fake-installation-token"}

    class _FakePrResponse:
        status_code = 201
        text = ""

        def json(self):
            return {"number": 42, "html_url": "https://github.com/acme/widgets/pull/42"}

    def _fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/access_tokens"):
            return _FakeTokenResponse()
        captured["url"] = url
        captured["json"] = json
        return _FakePrResponse()

    monkeypatch.setattr(
        github_app,
        "get_settings",
        lambda: Settings(github_app_id="123", github_app_private_key=_TEST_PRIVATE_KEY_PEM),
    )
    monkeypatch.setattr(github_app.httpx, "post", _fake_post)

    pr = GitHubAppAdapter().create_pull_request(
        "1", "acme", "widgets", "sf-task-abc12345", "main", "Fix the bug", "Real task output."
    )

    assert pr.number == 42
    assert pr.url == "https://github.com/acme/widgets/pull/42"
    assert captured["url"].endswith("/repos/acme/widgets/pulls")
    assert captured["json"] == {
        "title": "Fix the bug",
        "head": "sf-task-abc12345",
        "base": "main",
        "body": "Real task output.",
    }


def test_create_pull_request_raises_honestly_when_github_rejects_it(monkeypatch):
    class _FakeTokenResponse:
        status_code = 201

        def json(self):
            return {"token": "fake-installation-token"}

    class _FakeFailureResponse:
        status_code = 422
        text = '{"message": "A pull request already exists for acme:sf-task-abc."}'

        def json(self):
            return {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/access_tokens"):
            return _FakeTokenResponse()
        return _FakeFailureResponse()

    monkeypatch.setattr(
        github_app,
        "get_settings",
        lambda: Settings(github_app_id="123", github_app_private_key=_TEST_PRIVATE_KEY_PEM),
    )
    monkeypatch.setattr(github_app.httpx, "post", _fake_post)

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().create_pull_request("1", "acme", "widgets", "sf-task-abc", "main", "Fix the bug")

    assert "422" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Phase 18: reading a branch's real branch protection rules.
# ---------------------------------------------------------------------------


def test_get_branch_protection_reports_an_unprotected_branch_honestly(monkeypatch):
    class _FakeTokenResponse:
        status_code = 201

        def json(self):
            return {"token": "fake-installation-token"}

    class _FakeNotFoundResponse:
        status_code = 404
        text = '{"message": "Branch not protected"}'

        def json(self):
            return {}

    def _fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/access_tokens") or "/app/installations/" in url:
            return _FakeTokenResponse()
        return _FakeNotFoundResponse()

    monkeypatch.setattr(
        github_app,
        "get_settings",
        lambda: Settings(github_app_id="123", github_app_private_key=_TEST_PRIVATE_KEY_PEM),
    )
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    result = GitHubAppAdapter().get_branch_protection("1", "acme", "widgets", "main")

    assert result.protected is False
    assert result.required_status_checks == []
    assert result.required_approving_review_count == 0


def test_get_branch_protection_parses_the_real_configured_rules(monkeypatch):
    class _FakeTokenResponse:
        status_code = 201

        def json(self):
            return {"token": "fake-installation-token"}

    class _FakeProtectionResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "required_status_checks": {"contexts": ["ci/build", "ci/test"]},
                "required_pull_request_reviews": {"required_approving_review_count": 2},
            }

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "/branches/" in url:
            return _FakeProtectionResponse()
        return _FakeTokenResponse()

    monkeypatch.setattr(
        github_app,
        "get_settings",
        lambda: Settings(github_app_id="123", github_app_private_key=_TEST_PRIVATE_KEY_PEM),
    )
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    result = GitHubAppAdapter().get_branch_protection("1", "acme", "widgets", "main")

    assert result.protected is True
    assert result.required_status_checks == ["ci/build", "ci/test"]
    assert result.required_approving_review_count == 2


def test_get_branch_protection_fails_honestly_without_a_configured_app(monkeypatch):
    monkeypatch.setattr(github_app, "get_settings", lambda: Settings(github_app_id="", github_app_private_key=""))

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().get_branch_protection("1", "acme", "widgets", "main")

    assert "not configured" in exc_info.value.detail.lower()


def test_get_branch_protection_raises_honestly_on_an_unexpected_failure(monkeypatch):
    class _FakeTokenResponse:
        status_code = 201

        def json(self):
            return {"token": "fake-installation-token"}

    class _FakeErrorResponse:
        status_code = 500
        text = '{"message": "Internal error"}'

        def json(self):
            return {}

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "/branches/" in url:
            return _FakeErrorResponse()
        return _FakeTokenResponse()

    monkeypatch.setattr(
        github_app,
        "get_settings",
        lambda: Settings(github_app_id="123", github_app_private_key=_TEST_PRIVATE_KEY_PEM),
    )
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().get_branch_protection("1", "acme", "widgets", "main")

    assert "500" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Branch management, PR merge, and repository creation.
# ---------------------------------------------------------------------------


class _FakeTokenResponse:
    status_code = 201

    def json(self):
        return {"token": "fake-installation-token"}


def _configure_fake_app(monkeypatch):
    monkeypatch.setattr(
        github_app,
        "get_settings",
        lambda: Settings(github_app_id="123", github_app_private_key=_TEST_PRIVATE_KEY_PEM),
    )


def test_list_branches_parses_the_real_github_response(monkeypatch):
    class _FakeBranchesResponse:
        status_code = 200

        def json(self):
            return [
                {"name": "main", "commit": {"sha": "aaa111"}, "protected": True},
                {"name": "feature-x", "commit": {"sha": "bbb222"}, "protected": False},
            ]

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "/branches" in url:
            return _FakeBranchesResponse()
        return _FakeTokenResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    branches = GitHubAppAdapter().list_branches("1", "acme", "widgets")

    assert [b.name for b in branches] == ["main", "feature-x"]
    assert branches[0].commit_sha == "aaa111"
    assert branches[0].protected is True
    assert branches[1].protected is False


def test_create_branch_resolves_head_then_creates_the_real_ref(monkeypatch):
    captured = {}

    class _FakeBranchLookupResponse:
        status_code = 200

        def json(self):
            return {"commit": {"sha": "base-sha-123", "commit": {"message": ""}}}

    class _FakeRefResponse:
        status_code = 201
        text = ""

        def json(self):
            return {}

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "/branches/main" in url:
            return _FakeBranchLookupResponse()
        return _FakeTokenResponse()

    def _fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/access_tokens"):
            return _FakeTokenResponse()
        captured["url"] = url
        captured["json"] = json
        return _FakeRefResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", _fake_post)

    branch = GitHubAppAdapter().create_branch("1", "acme", "widgets", "sf-new-branch", "main")

    assert branch.name == "sf-new-branch"
    assert branch.commit_sha == "base-sha-123"
    assert captured["url"].endswith("/repos/acme/widgets/git/refs")
    assert captured["json"] == {"ref": "refs/heads/sf-new-branch", "sha": "base-sha-123"}


def test_create_branch_raises_honestly_when_github_rejects_it(monkeypatch):
    class _FakeBranchLookupResponse:
        status_code = 200

        def json(self):
            return {"commit": {"sha": "base-sha-123", "commit": {"message": ""}}}

    class _FakeFailureResponse:
        status_code = 422
        text = '{"message": "Reference already exists"}'

        def json(self):
            return {}

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "/branches/main" in url:
            return _FakeBranchLookupResponse()
        return _FakeTokenResponse()

    def _fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/access_tokens"):
            return _FakeTokenResponse()
        return _FakeFailureResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", _fake_post)

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().create_branch("1", "acme", "widgets", "sf-new-branch", "main")

    assert "422" in exc_info.value.detail


def test_compare_branches_parses_commits_and_builds_a_real_diff(monkeypatch):
    class _FakeCompareResponse:
        status_code = 200

        def json(self):
            return {
                "ahead_by": 2,
                "behind_by": 0,
                "commits": [
                    {
                        "sha": "c1",
                        "commit": {
                            "message": "Add feature",
                            "author": {"date": "2026-01-01T00:00:00Z"},
                        },
                        "author": {"login": "octocat"},
                    }
                ],
                "files": [{"filename": "a.py", "patch": "@@ -1 +1 @@\n-old\n+new"}],
            }

    def _fake_get(url, headers=None, params=None, timeout=None):
        if "/compare/" in url:
            return _FakeCompareResponse()
        return _FakeTokenResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    comparison = GitHubAppAdapter().compare_branches("1", "acme", "widgets", "main", "feature-x")

    assert comparison.ahead_by == 2
    assert comparison.behind_by == 0
    assert comparison.commits[0].sha == "c1"
    assert comparison.commits[0].message == "Add feature"
    assert comparison.commits[0].author_login == "octocat"
    assert "diff --git a/a.py b/a.py" in comparison.diff_text
    assert "+new" in comparison.diff_text


def test_merge_pull_request_reports_the_real_merge_result(monkeypatch):
    class _FakeMergeResponse:
        status_code = 200

        def json(self):
            return {"merged": True, "sha": "merged-sha", "message": "Pull Request successfully merged"}

    def _fake_put(url, headers=None, timeout=None):
        return _FakeMergeResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "put", _fake_put)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    result = GitHubAppAdapter().merge_pull_request("1", "acme", "widgets", 42)

    assert result.merged is True
    assert result.sha == "merged-sha"


def test_merge_pull_request_raises_honestly_with_githubs_real_rejection(monkeypatch):
    class _FakeFailureResponse:
        status_code = 405
        text = '{"message": "Pull Request is not mergeable"}'

        def json(self):
            return {}

    def _fake_put(url, headers=None, timeout=None):
        return _FakeFailureResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "put", _fake_put)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().merge_pull_request("1", "acme", "widgets", 42)

    assert "not mergeable" in exc_info.value.detail


def test_create_repository_refuses_honestly_on_a_personal_account(monkeypatch):
    class _FakeInstallationResponse:
        status_code = 200

        def json(self):
            return {"account": {"login": "octocat", "type": "User"}}

    def _fake_get(url, headers=None, params=None, timeout=None):
        return _FakeInstallationResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", lambda *a, **k: _FakeTokenResponse())

    with pytest.raises(GitProviderError) as exc_info:
        GitHubAppAdapter().create_repository("1", "new-repo")

    assert "personal" in exc_info.value.detail.lower()


def test_create_repository_creates_a_real_repo_under_an_organization(monkeypatch):
    captured = {}

    class _FakeInstallationResponse:
        status_code = 200

        def json(self):
            return {"account": {"login": "acme-org", "type": "Organization"}}

    class _FakeRepoResponse:
        status_code = 201
        text = ""

        def json(self):
            return {
                "name": "new-repo",
                "full_name": "acme-org/new-repo",
                "default_branch": "main",
                "html_url": "https://github.com/acme-org/new-repo",
                "owner": {"login": "acme-org"},
            }

    def _fake_get(url, headers=None, params=None, timeout=None):
        return _FakeInstallationResponse()

    def _fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/access_tokens"):
            return _FakeTokenResponse()
        captured["url"] = url
        captured["json"] = json
        return _FakeRepoResponse()

    _configure_fake_app(monkeypatch)
    monkeypatch.setattr(github_app.httpx, "get", _fake_get)
    monkeypatch.setattr(github_app.httpx, "post", _fake_post)

    created = GitHubAppAdapter().create_repository("1", "new-repo", private=True)

    assert created.full_name == "acme-org/new-repo"
    assert created.owner == "acme-org"
    assert captured["url"].endswith("/orgs/acme-org/repos")
    assert captured["json"]["name"] == "new-repo"
    assert captured["json"]["private"] is True


# ---------------------------------------------------------------------------
# Routes: branch panel, branch inspector, PR merge, new-repo creation.
# ---------------------------------------------------------------------------


def _connect_repository(client, headers, org, project):
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=headers,
    ).json()
    connection = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections",
        json={"git_installation_id": installation["id"], "owner": "acme", "name": "widgets"},
        headers=headers,
    ).json()
    return installation, connection


def test_list_connection_branches_route_returns_the_real_adapter_result(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "list_branches",
        lambda self, installation_id, owner, name: [
            BranchSummary(name="main", commit_sha="abc123", protected=True),
            BranchSummary(name="feature-x", commit_sha="def456"),
        ],
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    _installation, connection = _connect_repository(client, alice, org, project)

    r = client.get(
        f"/api/v1/projects/{project['id']}/repository-connections/{connection['id']}/branches",
        headers=alice,
    )
    assert r.status_code == 200, r.text
    names = [b["name"] for b in r.json()]
    assert names == ["main", "feature-x"]


def test_create_connection_branch_route_defaults_to_the_repositorys_default_branch(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    captured = {}

    def _fake_create_branch(self, installation_id, owner, name, new_branch, from_branch):
        captured["from_branch"] = from_branch
        return BranchSummary(name=new_branch, commit_sha="abc123")

    monkeypatch.setattr(GitHubAppAdapter, "create_branch", _fake_create_branch)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    _installation, connection = _connect_repository(client, alice, org, project)

    r = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections/{connection['id']}/branches",
        json={"name": "sf-new-feature"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "sf-new-feature"
    assert captured["from_branch"] == "main"


def test_compare_connection_branches_route_returns_the_real_diff(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "compare_branches",
        lambda self, installation_id, owner, name, base, head: BranchComparison(
            ahead_by=1,
            behind_by=0,
            commits=[BranchComparisonCommit(sha="c1", message="Add thing")],
            diff_text="diff --git a/x b/x\n+hi",
        ),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    _installation, connection = _connect_repository(client, alice, org, project)

    r = client.get(
        f"/api/v1/projects/{project['id']}/repository-connections/{connection['id']}/compare",
        params={"head": "feature-x"},
        headers=alice,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ahead_by"] == 1
    assert body["commits"][0]["sha"] == "c1"
    assert "+hi" in body["diff_text"]


def test_merge_task_pr_route_merges_the_real_open_pull_request(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )
    captured = {}

    def _fake_merge(self, installation_id, owner, name, pr_number):
        captured["pr_number"] = pr_number
        return MergeResult(merged=True, sha="merged-sha")

    monkeypatch.setattr(GitHubAppAdapter, "merge_pull_request", _fake_merge)

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    _connect_repository(client, alice, org, project)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Add a feature"}, headers=alice
    ).json()

    import uuid as uuid_module

    from app.core.database import SessionLocal
    from app.models.task import Task

    db = SessionLocal()
    db_task = db.get(Task, uuid_module.UUID(task["id"]))
    db_task.git_pr_number = 7
    db_task.git_pr_state = "open"
    db.commit()
    db.close()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/merge-pr", headers=alice)
    assert r.status_code == 200, r.text
    assert r.json()["merged"] is True
    assert captured["pr_number"] == 7

    r2 = client.get(f"/api/v1/projects/{project['id']}/tasks/{task['id']}", headers=alice)
    assert r2.json()["git_pr_state"] == "merged"


def test_merge_task_pr_route_conflicts_honestly_with_no_open_pr(client):
    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    task = client.post(
        f"/api/v1/projects/{project['id']}/tasks", json={"title": "Add a feature"}, headers=alice
    ).json()

    r = client.post(f"/api/v1/projects/{project['id']}/tasks/{task['id']}/merge-pr", headers=alice)
    assert r.status_code == 409


def test_create_repository_and_connect_route_creates_and_connects_a_real_repo(client, monkeypatch):
    monkeypatch.setattr(
        GitHubAppAdapter,
        "create_repository",
        lambda self, installation_id, name, private=True: CreatedRepository(
            owner="acme", name=name, full_name=f"acme/{name}", default_branch="main", html_url="https://x"
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_repository",
        lambda self, installation_id, owner, name: RepositorySummary(
            owner=owner, name=name, full_name=f"{owner}/{name}", default_branch="main", private=True
        ),
    )
    monkeypatch.setattr(
        GitHubAppAdapter,
        "get_branch_head_commit",
        lambda self, installation_id, owner, name, branch: CommitSummary(sha="abc123"),
    )

    alice = _register_and_login(client, "alice@example.com", "Alice")
    org, project = _org_and_project(client, alice)
    installation = client.post(
        f"/api/v1/organizations/{org['id']}/git-installations",
        json={"external_installation_id": "1"},
        headers=alice,
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/repository-connections/create-repository",
        json={"git_installation_id": installation["id"], "name": "brand-new-repo"},
        headers=alice,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["full_name"] == "acme/brand-new-repo"
    assert body["status"] == "connected"

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
from app.services.git_provider.base import GitProviderError, RepositorySummary, CommitSummary
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
    assert "already exists" in exc_info.value.detail

"""Phase 14: task-specific Git worktrees and real execution.

These exercise `app/services/git_worktree.py` against a genuine local Git
repository acting as the "remote" -- the clone, branch checkout, commit and
diff are all real `git` invocations. Only the network edge (which URL
`GitHubAppAdapter` hands back for a given installation) is stubbed, exactly
like the rest of this suite stubs provider network calls while keeping the
decision logic real.
"""

import subprocess
import uuid
from pathlib import Path

import pytest

from app.models.git_integration import GitInstallation, GitProvider, RepositoryConnection
from app.models.task import Task
from app.services import git_worktree
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.github_app import GitHubAppAdapter


def _run(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def remote_repo(tmp_path):
    """A real local Git repository standing in for a remote GitHub repo."""
    repo = tmp_path / "remote"
    repo.mkdir()
    _run(["init", "-b", "main"], repo)
    _run(["config", "user.email", "seed@example.com"], repo)
    _run(["config", "user.name", "Seed"], repo)
    (repo / "README.md").write_text("hello\n")
    _run(["add", "-A"], repo)
    _run(["commit", "-m", "Initial commit"], repo)
    return repo


def _fake_task():
    return Task(id=uuid.uuid4(), project_id=uuid.uuid4(), title="Do thing", created_by_user_id=uuid.uuid4())


def _fake_connection(default_branch="main"):
    installation = GitInstallation(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        provider=GitProvider.GITHUB,
        external_installation_id="1",
        created_by_user_id=uuid.uuid4(),
    )
    connection = RepositoryConnection(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        git_installation_id=installation.id,
        owner="acme",
        name="widgets",
        full_name="acme/widgets",
        default_branch=default_branch,
        created_by_user_id=uuid.uuid4(),
    )
    connection.installation = installation
    return connection


def test_prepare_worktree_clones_and_checks_out_a_real_branch(monkeypatch, remote_repo, tmp_path):
    monkeypatch.setattr(
        GitHubAppAdapter, "get_authenticated_clone_url", lambda self, *a, **k: str(remote_repo)
    )
    monkeypatch.setattr(
        git_worktree, "_worktree_root", lambda: tmp_path / "worktrees"
    )

    task = _fake_task()
    connection = _fake_connection()

    result = git_worktree.prepare_worktree(task, connection)

    assert Path(result.path).is_dir()
    assert (Path(result.path) / "README.md").read_text() == "hello\n"
    assert result.branch_name.startswith("sf-task-")
    assert result.base_branch == "main"

    branch_proc = subprocess.run(
        ["git", "branch", "--show-current"], cwd=result.path, capture_output=True, text=True
    )
    assert branch_proc.stdout.strip() == result.branch_name


def test_prepare_worktree_raises_honestly_when_provider_auth_fails(monkeypatch, tmp_path):
    def _fail(self, *a, **k):
        raise GitProviderError("GitHub App not configured on this backend.")

    monkeypatch.setattr(GitHubAppAdapter, "get_authenticated_clone_url", _fail)
    monkeypatch.setattr(git_worktree, "_worktree_root", lambda: tmp_path / "worktrees")

    with pytest.raises(git_worktree.WorktreeError) as exc_info:
        git_worktree.prepare_worktree(_fake_task(), _fake_connection())

    assert "not configured" in exc_info.value.detail.lower()


def test_prepare_worktree_raises_honestly_when_clone_fails(monkeypatch, tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    monkeypatch.setattr(
        GitHubAppAdapter, "get_authenticated_clone_url", lambda self, *a, **k: str(nonexistent)
    )
    monkeypatch.setattr(git_worktree, "_worktree_root", lambda: tmp_path / "worktrees")

    with pytest.raises(git_worktree.WorktreeError):
        git_worktree.prepare_worktree(_fake_task(), _fake_connection())


def test_collect_diff_is_empty_when_the_agent_changed_nothing(remote_repo, tmp_path):
    clone_dir = tmp_path / "clone"
    _run(["clone", str(remote_repo), str(clone_dir)], tmp_path)
    _run(["checkout", "-b", "sf-task-test"], clone_dir)

    diff = git_worktree.collect_diff(str(clone_dir), "Task execution")

    assert diff.changed_files == []
    assert diff.diff_text == ""


def test_collect_diff_captures_a_real_file_change(remote_repo, tmp_path):
    clone_dir = tmp_path / "clone"
    _run(["clone", str(remote_repo), str(clone_dir)], tmp_path)
    _run(["checkout", "-b", "sf-task-test"], clone_dir)
    _run(["config", "user.email", "factory@software-factory.local"], clone_dir)
    _run(["config", "user.name", "Software Factory"], clone_dir)

    (clone_dir / "new_feature.py").write_text("print('real change')\n")

    diff = git_worktree.collect_diff(str(clone_dir), "Add new_feature.py")

    assert diff.changed_files == ["new_feature.py"]
    assert "real change" in diff.diff_text
    assert "+print" in diff.diff_text

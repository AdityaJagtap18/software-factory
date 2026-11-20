"""Phase 14: task-specific Git worktrees and real execution.
Phase 15: pushing a task's branch to the remote (below).

These exercise `app/services/git_worktree.py` against a genuine local Git
repository acting as the "remote" -- the clone, branch checkout, commit,
diff, and push are all real `git` invocations. Only the network edge
(which URL `GitHubAppAdapter` hands back for a given installation) is
stubbed, exactly like the rest of this suite stubs provider network calls
while keeping the decision logic real.
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

    diff = git_worktree.collect_diff(str(clone_dir), "main", "Task execution")

    assert diff.changed_files == []
    assert diff.diff_text == ""


def test_collect_diff_captures_a_real_file_change(remote_repo, tmp_path):
    clone_dir = tmp_path / "clone"
    _run(["clone", str(remote_repo), str(clone_dir)], tmp_path)
    _run(["checkout", "-b", "sf-task-test"], clone_dir)
    _run(["config", "user.email", "factory@software-factory.local"], clone_dir)
    _run(["config", "user.name", "Software Factory"], clone_dir)

    (clone_dir / "new_feature.py").write_text("print('real change')\n")

    diff = git_worktree.collect_diff(str(clone_dir), "main", "Add new_feature.py")

    assert diff.changed_files == ["new_feature.py"]
    assert "real change" in diff.diff_text
    assert "+print" in diff.diff_text


def test_collect_diff_is_cumulative_across_two_real_runs(remote_repo, tmp_path):
    """A follow-up turn's `collect_diff` call must still show the FIRST
    turn's changes too -- it diffs against the base branch, not HEAD~1."""
    clone_dir = tmp_path / "clone"
    _run(["clone", str(remote_repo), str(clone_dir)], tmp_path)
    _run(["checkout", "-b", "sf-task-test"], clone_dir)
    _run(["config", "user.email", "factory@software-factory.local"], clone_dir)
    _run(["config", "user.name", "Software Factory"], clone_dir)

    (clone_dir / "first.py").write_text("print('first turn')\n")
    first = git_worktree.collect_diff(str(clone_dir), "main", "First turn")
    assert first.changed_files == ["first.py"]

    (clone_dir / "second.py").write_text("print('second turn')\n")
    second = git_worktree.collect_diff(str(clone_dir), "main", "Second turn")

    assert sorted(second.changed_files) == ["first.py", "second.py"]
    assert "first turn" in second.diff_text
    assert "second turn" in second.diff_text


def test_resume_worktree_reuses_the_existing_directory(monkeypatch, remote_repo, tmp_path):
    monkeypatch.setattr(
        GitHubAppAdapter, "get_authenticated_clone_url", lambda self, *a, **k: str(remote_repo)
    )
    monkeypatch.setattr(git_worktree, "_worktree_root", lambda: tmp_path / "worktrees")

    task = _fake_task()
    connection = _fake_connection()
    first_run = git_worktree.prepare_worktree(task, connection)
    (Path(first_run.path) / "turn_one.py").write_text("print('turn one')\n")
    git_worktree.collect_diff(first_run.path, first_run.base_branch, "Turn one")

    resumed = git_worktree.resume_worktree(task, connection)

    assert resumed.path == first_run.path
    assert resumed.branch_name == first_run.branch_name
    # The first turn's real file is still there -- this is a reuse, not a
    # fresh clone that would have wiped it out.
    assert (Path(resumed.path) / "turn_one.py").exists()


def test_resume_worktree_raises_honestly_when_nothing_to_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(git_worktree, "_worktree_root", lambda: tmp_path / "worktrees")

    with pytest.raises(git_worktree.WorktreeError):
        git_worktree.resume_worktree(_fake_task(), _fake_connection())


def test_push_branch_pushes_the_real_branch_to_the_remote(remote_repo, tmp_path):
    clone_dir = tmp_path / "clone"
    _run(["clone", str(remote_repo), str(clone_dir)], tmp_path)
    _run(["checkout", "-b", "sf-task-push"], clone_dir)
    _run(["config", "user.email", "factory@software-factory.local"], clone_dir)
    _run(["config", "user.name", "Software Factory"], clone_dir)
    (clone_dir / "new_feature.py").write_text("print('pushed')\n")
    git_worktree.collect_diff(str(clone_dir), "main", "Add new_feature.py")

    git_worktree.push_branch(str(clone_dir), "sf-task-push")

    branches = subprocess.run(
        ["git", "branch", "--list", "sf-task-push"], cwd=remote_repo, capture_output=True, text=True
    )
    assert "sf-task-push" in branches.stdout


def test_push_branch_raises_honestly_and_redacts_the_secret_on_failure(remote_repo, tmp_path):
    clone_dir = tmp_path / "clone"
    _run(["clone", str(remote_repo), str(clone_dir)], tmp_path)
    _run(["checkout", "-b", "sf-task-push"], clone_dir)
    secret_url = "https://x-access-token:super-secret-token@localhost:1/no/such/repo.git"
    _run(["remote", "set-url", "origin", secret_url], clone_dir)

    with pytest.raises(git_worktree.WorktreeError) as exc_info:
        git_worktree.push_branch(str(clone_dir), "sf-task-push", clone_secret="super-secret-token@")

    assert "super-secret-token" not in exc_info.value.detail

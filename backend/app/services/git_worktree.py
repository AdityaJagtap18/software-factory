"""Phase 14: task-specific Git worktrees and real execution.

When a task's project has a connected repository, the task runs against a
real, isolated checkout of that repository on its own branch -- not just a
bare prompt with no codebase. This module shells out to the real `git`
binary; nothing here fabricates a clone, a branch, or a diff. Any failure
(provider auth, network, `git` itself) is raised as `WorktreeError` with
the real reason, and the authenticated clone URL (which embeds a real,
short-lived credential) is never allowed to leak into an error message.
"""

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import get_settings
from app.models.git_integration import RepositoryConnection
from app.models.task import Task
from app.services.git_provider.base import GitProviderError
from app.services.git_provider.registry import get_git_provider

_GIT_TIMEOUT_SECONDS = 180.0
_MAX_DIFF_CHARS = 200_000


class WorktreeError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class WorktreeResult:
    path: str
    branch_name: str
    base_branch: str
    # The real credential embedded in the clone URL, kept only so a later
    # `push_branch` call can redact it from any error message -- never
    # persisted on the task row.
    clone_secret: str = field(default="", repr=False)


@dataclass(frozen=True)
class DiffResult:
    changed_files: list = field(default_factory=list)
    diff_text: str = ""


def _force_remove_readonly(func, path, exc_info) -> None:
    # Git marks pack files read-only; a plain rmtree silently leaves them
    # behind on Windows (even with ignore_errors=True), so a reused task
    # directory's previous clone can make the next real clone fail with
    # "destination path already exists and is not an empty directory."
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _worktree_root() -> Path:
    # Always absolute: a relative path here would reach a adapter (e.g. a
    # `docker run -v` bind mount) as a relative host path, which Docker
    # rejects outright rather than resolving against this process's cwd.
    root = Path(get_settings().worktree_root_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "<redacted>")
    return text[:1000]


def _run_git(args: list[str], cwd: str, secret: str = "") -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeError(_sanitize(str(exc), secret)) from exc
    if proc.returncode != 0:
        raise WorktreeError(_sanitize(proc.stderr or proc.stdout or f"'git {args[0]}' failed", secret))
    return proc


def prepare_worktree(task: Task, connection: RepositoryConnection) -> WorktreeResult:
    """Clones the real connected repository at its default branch into an
    isolated directory dedicated to this task, and checks out a new real
    branch for it. Raises `WorktreeError` with the real reason (provider
    not configured, clone failure, ...) rather than ever returning a
    fabricated worktree."""
    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        raise WorktreeError(f"Unknown git provider '{connection.installation.provider.value}'.")

    try:
        clone_url = adapter.get_authenticated_clone_url(
            connection.installation.external_installation_id, connection.owner, connection.name
        )
    except GitProviderError as exc:
        raise WorktreeError(exc.detail) from exc

    token = clone_url.split("://", 1)[1].split("@", 1)[0] if "@" in clone_url else ""
    secret = f"{token}@" if token else clone_url

    target = _worktree_root() / str(task.id)
    if target.exists():
        shutil.rmtree(target, onerror=_force_remove_readonly)

    base_branch = connection.default_branch or "main"
    try:
        proc = subprocess.run(
            [
                "git", "clone", "--branch", base_branch, "--single-branch", "--depth", "1",
                clone_url, str(target),
            ],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorktreeError(_sanitize(str(exc), secret)) from exc
    if proc.returncode != 0:
        raise WorktreeError(_sanitize(proc.stderr or proc.stdout or "git clone failed", secret))

    clone_dir = str(target)
    branch_name = f"sf-task-{str(task.id)[:8]}"
    _run_git(["checkout", "-b", branch_name], clone_dir, secret)
    _run_git(["config", "user.email", "factory@software-factory.local"], clone_dir, secret)
    _run_git(["config", "user.name", "Software Factory"], clone_dir, secret)

    return WorktreeResult(
        path=clone_dir, branch_name=branch_name, base_branch=base_branch, clone_secret=secret
    )


def resume_worktree(task: Task, connection: RepositoryConnection) -> WorktreeResult:
    """Reuses the real, already-cloned worktree from a task's first run for
    a follow-up turn, so the agent continues in a checkout that already
    contains its own earlier changes rather than starting over. Refreshes
    `origin`'s URL with a newly-minted credential first, since a GitHub App
    installation token is short-lived and the one from the original clone
    may have expired by the time a follow-up arrives. Raises `WorktreeError`
    if there is no prior worktree to resume -- never fabricates one."""
    target = _worktree_root() / str(task.id)
    if not target.exists():
        raise WorktreeError("This task has no existing workspace to continue in. Start it first.")

    adapter = get_git_provider(connection.installation.provider.value)
    if adapter is None:
        raise WorktreeError(f"Unknown git provider '{connection.installation.provider.value}'.")
    try:
        clone_url = adapter.get_authenticated_clone_url(
            connection.installation.external_installation_id, connection.owner, connection.name
        )
    except GitProviderError as exc:
        raise WorktreeError(exc.detail) from exc

    token = clone_url.split("://", 1)[1].split("@", 1)[0] if "@" in clone_url else ""
    secret = f"{token}@" if token else clone_url

    clone_dir = str(target)
    _run_git(["remote", "set-url", "origin", clone_url], clone_dir, secret)

    branch_name = task.git_branch_name or f"sf-task-{str(task.id)[:8]}"
    base_branch = task.git_base_branch or connection.default_branch or "main"
    return WorktreeResult(
        path=clone_dir, branch_name=branch_name, base_branch=base_branch, clone_secret=secret
    )


def collect_diff(worktree_path: str, base_branch: str, commit_message: str) -> DiffResult:
    """Stages every real filesystem change the agent made inside
    `worktree_path`, commits it on the task's branch if there is anything
    to commit, and returns the real CUMULATIVE diff against `base_branch`
    (its `origin/<base_branch>` remote-tracking ref, set by the original
    clone) -- not just the latest commit. This matters once a task has had
    more than one real run (a follow-up turn, see `execute_followup`):
    without diffing against the base, a second run's diff would silently
    drop the first run's changes. A worktree with no changes at all across
    every run returns an empty `DiffResult` -- never a fabricated one."""
    _run_git(["add", "-A"], worktree_path)
    status = _run_git(["status", "--porcelain"], worktree_path)
    if status.stdout.strip():
        _run_git(["commit", "-m", commit_message or "Task execution"], worktree_path)

    base_ref = f"origin/{base_branch}"
    name_proc = _run_git(["diff", base_ref, "HEAD", "--name-only"], worktree_path)
    changed_files = [line.strip() for line in name_proc.stdout.splitlines() if line.strip()]
    if not changed_files:
        return DiffResult()
    diff_proc = _run_git(["diff", base_ref, "HEAD"], worktree_path)
    return DiffResult(changed_files=changed_files, diff_text=diff_proc.stdout[:_MAX_DIFF_CHARS])


def push_branch(worktree_path: str, branch_name: str, clone_secret: str = "") -> None:
    """Pushes the task's real branch to the remote the worktree was cloned
    from (the `origin` remote's URL, embedded credential included, was set
    by the real `git clone` in `prepare_worktree`). Raises `WorktreeError`
    with the real reason -- e.g. the credential expired -- on failure,
    with the credential redacted from the message."""
    _run_git(["push", "origin", branch_name], worktree_path, clone_secret)


def cleanup_worktree(path: str) -> None:
    shutil.rmtree(path, onerror=_force_remove_readonly)

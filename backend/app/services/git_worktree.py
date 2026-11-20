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

    return WorktreeResult(path=clone_dir, branch_name=branch_name, base_branch=base_branch)


def collect_diff(worktree_path: str, commit_message: str) -> DiffResult:
    """Stages every real filesystem change the agent made inside
    `worktree_path`, commits it on the task's branch if there is anything
    to commit, and returns the real diff. An agent run that touched no
    files returns an empty `DiffResult` -- never a fabricated one."""
    _run_git(["add", "-A"], worktree_path)
    status = _run_git(["status", "--porcelain"], worktree_path)
    if not status.stdout.strip():
        return DiffResult()

    _run_git(["commit", "-m", commit_message or "Task execution"], worktree_path)
    name_proc = _run_git(["diff", "HEAD~1", "HEAD", "--name-only"], worktree_path)
    changed_files = [line.strip() for line in name_proc.stdout.splitlines() if line.strip()]
    diff_proc = _run_git(["diff", "HEAD~1", "HEAD"], worktree_path)
    return DiffResult(changed_files=changed_files, diff_text=diff_proc.stdout[:_MAX_DIFF_CHARS])


def cleanup_worktree(path: str) -> None:
    shutil.rmtree(path, onerror=_force_remove_readonly)

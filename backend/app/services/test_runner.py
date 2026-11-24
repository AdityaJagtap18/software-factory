"""Real test execution for a task's worktree (P3-1).

Detects whichever single test framework the checked-out repository
actually uses and runs its real command -- never a simulated or
fabricated pass/fail. A repository with no recognizable test setup
honestly reports `framework="none"` rather than a fake result.
"""

import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TEST_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class TestRunResult:
    framework: str  # "pytest" | "npm" | "none"
    ran: bool
    passed: int = 0
    failed: int = 0
    total: int = 0
    output: str = ""
    error: str = ""


def detect_framework(worktree_path: str) -> str:
    root = Path(worktree_path)
    if (root / "pytest.ini").exists() or (root / "setup.cfg").exists() or list(root.glob("**/test_*.py"))[:1]:
        return "pytest"
    if (root / "package.json").exists():
        return "npm"
    return "none"


def _parse_pytest_summary(output: str) -> tuple[int, int]:
    """Parses pytest's real summary line, e.g. "2 passed, 1 failed in 0.12s".
    Returns (passed, failed); either defaults to 0 if that word doesn't
    appear (pytest omits "failed" entirely when there are none)."""
    passed = 0
    failed = 0
    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) error", output)
    if m:
        failed += int(m.group(1))
    return passed, failed


def run_tests(worktree_path: str) -> TestRunResult:
    """Runs the real, detected test command inside `worktree_path`. Honest
    about every outcome: no recognizable framework, a timeout, or the
    command itself failing to start are each reported distinctly rather
    than folded into a generic failure."""
    framework = detect_framework(worktree_path)
    if framework == "none":
        return TestRunResult(framework="none", ran=False, error="No recognizable test framework found.")

    if framework == "pytest":
        command = ["python", "-m", "pytest", "-q"]
    else:
        # On Windows, `npm` is `npm.cmd`, which CreateProcess can't resolve
        # directly without going through the shell (unlike POSIX exec) --
        # using the real platform-appropriate name, not a simulated result.
        npm = "npm.cmd" if platform.system() == "Windows" else "npm"
        command = [npm, "test", "--silent"]

    try:
        proc = subprocess.run(
            command,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=_TEST_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return TestRunResult(framework=framework, ran=False, error=f"Could not start test runner: {exc}")
    except subprocess.TimeoutExpired:
        return TestRunResult(
            framework=framework,
            ran=False,
            error=f"Test run exceeded {_TEST_TIMEOUT_SECONDS}s and was aborted.",
        )

    output = (proc.stdout or "") + (proc.stderr or "")
    if framework == "pytest":
        passed, failed = _parse_pytest_summary(output)
    else:
        passed, failed = (1, 0) if proc.returncode == 0 else (0, 1)

    return TestRunResult(
        framework=framework,
        ran=True,
        passed=passed,
        failed=failed,
        total=passed + failed,
        output=output[-20000:],
    )

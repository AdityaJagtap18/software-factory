"""The Git Provider Interface.

Every Git host (GitHub first, GitLab/Bitbucket later) is exposed to the
rest of the platform through this interface, mirroring the Common Agent
Runtime Interface (`app/services/agent_runtime/base.py`): a new provider
means a new adapter class, never a change to the routes or sync logic
that call it. An adapter never claims a repository is reachable or a
commit is real without having actually asked the provider -- a
misconfigured or unreachable provider reports `connected=False` /
raises `GitProviderError` with the real detail, never a fabricated
success.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


class GitProviderError(Exception):
    """Raised when a real call to the provider's API fails. `detail` is
    the real, specific reason -- never a generic 'something went wrong'."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class GitHealthCheckResult:
    connected: bool
    account_login: str = ""
    detail: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class RepositorySummary:
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool


@dataclass(frozen=True)
class CommitSummary:
    sha: str
    message: str = ""


@dataclass(frozen=True)
class PullRequestSummary:
    number: int
    url: str
    state: str = "open"


@dataclass(frozen=True)
class BranchProtectionSummary:
    """What the provider's own branch protection rules require for a
    branch -- `protected=False` means GitHub reports no rules configured,
    never a guess from an unrelated failure (see `get_branch_protection`)."""

    protected: bool
    required_status_checks: list[str] = field(default_factory=list)
    required_approving_review_count: int = 0


@dataclass(frozen=True)
class BranchSummary:
    name: str
    commit_sha: str
    protected: bool = False


@dataclass(frozen=True)
class BranchComparisonCommit:
    sha: str
    message: str
    author_login: str = ""
    authored_at: datetime | None = None


@dataclass(frozen=True)
class BranchComparison:
    """The real result of comparing `head` against `base` -- mirrors
    GitHub's own compare API (`ahead_by`/`behind_by` are the real counts
    GitHub reports, never derived locally)."""

    ahead_by: int
    behind_by: int
    commits: list[BranchComparisonCommit] = field(default_factory=list)
    diff_text: str = ""


@dataclass(frozen=True)
class MergeResult:
    merged: bool
    sha: str = ""
    message: str = ""


@dataclass(frozen=True)
class CreatedRepository:
    owner: str
    name: str
    full_name: str
    default_branch: str
    html_url: str


class GitProviderAdapter(ABC):
    """Base class every Git provider adapter implements."""

    slug: str
    display_name: str

    @abstractmethod
    def health_check(self, external_installation_id: str) -> GitHealthCheckResult:
        """A real check that this installation's credentials can currently
        reach the provider's API. Must never return `connected=True`
        without having actually observed a successful call."""

    @abstractmethod
    def list_repositories(self, external_installation_id: str) -> list[RepositorySummary]:
        """The real set of repositories this installation currently grants
        access to. Raises `GitProviderError` on any failure -- never
        returns a fabricated or stale list."""

    @abstractmethod
    def get_repository(self, external_installation_id: str, owner: str, name: str) -> RepositorySummary:
        """The real, current metadata for one repository."""

    @abstractmethod
    def get_branch_head_commit(
        self, external_installation_id: str, owner: str, name: str, branch: str
    ) -> CommitSummary:
        """The real current HEAD commit of one branch."""

    @abstractmethod
    def get_authenticated_clone_url(self, external_installation_id: str, owner: str, name: str) -> str:
        """A real HTTPS clone URL with a short-lived, real credential
        embedded, usable directly with `git clone` -- never a long-lived
        personal access token. Raises `GitProviderError` with the real
        reason if a credential cannot be obtained."""

    @abstractmethod
    def create_pull_request(
        self,
        external_installation_id: str,
        owner: str,
        name: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str = "",
    ) -> PullRequestSummary:
        """Opens a real pull request from `head_branch` into `base_branch`
        via the provider's API. `head_branch` must already exist on the
        remote (push it first). Raises `GitProviderError` with the real
        reason on failure -- never a fabricated PR number or URL."""

    @abstractmethod
    def get_branch_protection(
        self, external_installation_id: str, owner: str, name: str, branch: str
    ) -> BranchProtectionSummary:
        """The real branch protection rules GitHub has configured for
        `branch`, if any. A branch with no rules configured is a real,
        successful result (`protected=False`), not an error. Raises
        `GitProviderError` only when the check itself could not be made."""

    @abstractmethod
    def list_branches(self, external_installation_id: str, owner: str, name: str) -> list[BranchSummary]:
        """The repository's real, current branches. Raises
        `GitProviderError` on failure -- never a fabricated or stale list."""

    @abstractmethod
    def create_branch(
        self, external_installation_id: str, owner: str, name: str, new_branch: str, from_branch: str
    ) -> BranchSummary:
        """Creates a real branch `new_branch` pointed at `from_branch`'s
        current HEAD via the provider's refs API. Raises `GitProviderError`
        with the real reason on failure (e.g. the branch already exists)."""

    @abstractmethod
    def compare_branches(
        self, external_installation_id: str, owner: str, name: str, base: str, head: str
    ) -> BranchComparison:
        """The real commits and diff of `head` against `base`, read-only --
        never a locally-derived guess. Raises `GitProviderError` on
        failure (e.g. one of the branches does not exist)."""

    @abstractmethod
    def merge_pull_request(
        self, external_installation_id: str, owner: str, name: str, pr_number: int
    ) -> MergeResult:
        """Merges a real, already-open pull request via the provider's own
        merge endpoint -- this backend never performs the merge itself and
        never bypasses the provider's own protection/check enforcement.
        Raises `GitProviderError` with the provider's real rejection reason
        (failing checks, missing reviews, merge conflicts, ...) on failure."""

    @abstractmethod
    def create_repository(
        self, external_installation_id: str, name: str, private: bool = True
    ) -> CreatedRepository:
        """Creates a real, brand-new repository under this installation's
        account via the provider's API. Raises `GitProviderError` with the
        real reason on failure (e.g. a repository with that name already
        exists)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.git_integration import (
    InstallationStatus,
    RepositoryConnectionStatus,
    WebhookConfigStatus,
)


class GitInstallationCreate(BaseModel):
    external_installation_id: str
    account_login: str = ""


class GitInstallationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    provider: str
    external_installation_id: str
    account_login: str
    status: InstallationStatus
    last_error: str
    last_health_check_at: datetime | None

    model_config = {"from_attributes": True}


class RepositorySummarySchema(BaseModel):
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool


class RepositoryConnectionCreate(BaseModel):
    git_installation_id: UUID
    owner: str
    name: str
    selected_working_branches: list[str] = []


class RepositoryConnectionResponse(BaseModel):
    id: UUID
    project_id: UUID
    git_installation_id: UUID
    owner: str
    name: str
    full_name: str
    default_branch: str
    selected_working_branches: list[str]
    status: RepositoryConnectionStatus
    permission_scope: str
    last_error: str
    last_successful_sync_at: datetime | None
    last_observed_commit_sha: str
    webhook_config_status: WebhookConfigStatus

    model_config = {"from_attributes": True}


class BranchSummarySchema(BaseModel):
    name: str
    commit_sha: str
    protected: bool = False


class BranchCreate(BaseModel):
    name: str
    from_branch: str = ""


class BranchComparisonCommitSchema(BaseModel):
    sha: str
    message: str
    author_login: str = ""
    authored_at: datetime | None = None


class BranchComparisonSchema(BaseModel):
    ahead_by: int
    behind_by: int
    commits: list[BranchComparisonCommitSchema]
    diff_text: str


class MergePullRequestResult(BaseModel):
    merged: bool
    sha: str = ""
    message: str = ""


class RepositoryCreate(BaseModel):
    git_installation_id: UUID
    name: str
    private: bool = True
    selected_working_branches: list[str] = []


class WebhookEventResponse(BaseModel):
    id: UUID
    event_type: str
    repository_full_name: str
    signature_verified: bool
    processing_result: str
    created_at: datetime

    model_config = {"from_attributes": True}

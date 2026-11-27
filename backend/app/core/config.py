from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SF_", extra="ignore")

    # "development" (the default) is the only environment where the
    # placeholder secrets below and the dev-login bypass are tolerated.
    # Set SF_ENVIRONMENT=production (or staging, etc.) for any shared or
    # non-local deployment -- this flips on the fail-fast checks in
    # app/main.py and hard-disables dev-login regardless of the
    # dev_quick_login_enabled flag below.
    environment: str = "development"
    database_url: str = "postgresql+psycopg2://sf:sf@localhost:5433/software_factory"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    cors_origins: list[str] = ["http://localhost:4200"]
    credential_encryption_key: str = "dev-credential-key-change-me"
    neo4j_uri: str = "bolt://localhost:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "sfgraphpass123"
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""
    github_api_base_url: str = "https://api.github.com"
    worktree_root_dir: str = "data/worktrees"
    # Local-dev convenience only: lets the login screen offer a one-click
    # "Quick sign in" that skips typing a password. Both must be set
    # explicitly in a (gitignored) .env -- empty/false by default means the
    # feature is off and /auth/dev-login always 404s.
    dev_quick_login_enabled: bool = False
    dev_quick_login_email: str = ""
    gemini_api_key: str = ""
    # Phase 2 (P2-3): per-runtime Docker image for sandboxed local-CLI
    # execution, each with that runtime's real CLI pre-installed. Empty
    # (the default) means "not yet built/configured" -- that adapter
    # honestly keeps running directly on the backend host (today's only
    # mode) rather than claiming sandboxing that doesn't exist. Setting
    # one of these to a real image name switches that adapter to run
    # inside Docker (filesystem-jailed to the task worktree, memory/CPU
    # limited) for every future execution -- see
    # `app/services/agent_runtime/adapters.py::_run_cli_prompt_streaming_sandboxed`.
    claude_code_sandbox_image: str = ""
    codex_sandbox_image: str = ""
    gemini_cli_sandbox_image: str = ""
    qwen_sandbox_image: str = ""

    @field_validator("github_app_private_key")
    @classmethod
    def _unescape_private_key_newlines(cls, value: str) -> str:
        # A .env-style file can't reliably hold a real multi-line PEM, so
        # this is normally supplied as one line with literal "\n" escapes;
        # turn those back into real newlines for the PyJWT/cryptography
        # call that actually signs with it.
        return value.replace("\\n", "\n") if "\\n" in value else value

    @property
    def is_local_dev(self) -> bool:
        return self.environment.lower() in ("development", "local", "dev")


_PLACEHOLDER_JWT_SECRET = "dev-secret-change-me"
_PLACEHOLDER_CREDENTIAL_KEY = "dev-credential-key-change-me"


def _validate_non_local_settings(settings: Settings) -> None:
    """Fail fast rather than silently run a shared/production deployment
    with the insecure local-dev defaults (P0-1/P0-2 of the security
    hygiene audit)."""
    if settings.is_local_dev:
        return
    problems = []
    if settings.jwt_secret == _PLACEHOLDER_JWT_SECRET:
        problems.append("SF_JWT_SECRET is still the placeholder default")
    if settings.credential_encryption_key == _PLACEHOLDER_CREDENTIAL_KEY:
        problems.append("SF_CREDENTIAL_ENCRYPTION_KEY is still the placeholder default")
    if settings.dev_quick_login_enabled:
        problems.append("SF_DEV_QUICK_LOGIN_ENABLED is true")
    if problems:
        raise RuntimeError(
            "Refusing to start with SF_ENVIRONMENT="
            f"'{settings.environment}': {'; '.join(problems)}. "
            "These are only safe in a local-dev environment."
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _validate_non_local_settings(settings)
    return settings

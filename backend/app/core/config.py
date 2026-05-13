"""Application settings and environment configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.auth_mode import AuthMode
from app.core.rate_limit_backend import RateLimitBackend

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
LOCAL_AUTH_TOKEN_MIN_LENGTH = 50
LOCAL_AUTH_TOKEN_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "changeme",
        "replace-me",
        "replace-with-strong-random-token",
    },
)


class Settings(BaseSettings):
    """Typed runtime configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        # Load `backend/.env` regardless of current working directory.
        # (Important when running uvicorn from repo root or via a process manager.)
        env_file=[DEFAULT_ENV_FILE, ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/openclaw_agency"

    # Auth mode: "clerk" for Clerk JWT auth, "local" for shared bearer token auth.
    auth_mode: AuthMode
    local_auth_token: str = ""

    # Clerk auth (auth only; roles stored in DB)
    clerk_secret_key: str = ""
    clerk_api_url: str = "https://api.clerk.com"
    clerk_verify_iat: bool = True
    clerk_leeway: float = 10.0

    cors_origins: str = ""
    base_url: str = ""
    gateway_origin: str = ""  # Origin sent on WebSocket upgrade; defaults to base_url if empty

    # Security response headers (set to blank to disable a specific header)
    security_header_x_content_type_options: str = "nosniff"
    security_header_x_frame_options: str = "DENY"
    security_header_referrer_policy: str = "strict-origin-when-cross-origin"
    security_header_permissions_policy: str = ""

    # Webhook payload size limit in bytes (default 1 MB).
    webhook_max_payload_bytes: int = 1_048_576

    # Rate limiting
    rate_limit_backend: RateLimitBackend = RateLimitBackend.MEMORY
    rate_limit_redis_url: str = ""
    # Set to False to disable all rate limiting (trusted self-hosted deployments).
    rate_limit_enabled: bool = True
    # Agent auth limiter (applies per client IP).
    agent_auth_rate_limit_max: int = 20
    agent_auth_rate_limit_window: float = 60.0
    # Webhook ingest limiter (applies per client IP).
    webhook_rate_limit_max: int = 60
    webhook_rate_limit_window: float = 60.0
    # MCP tool-call limiter (applies per board).
    mcp_rate_limit_max: int = 10
    mcp_rate_limit_window: float = 60.0

    # Trusted reverse-proxy IPs/CIDRs for client-IP extraction from
    # Forwarded / X-Forwarded-For headers.  Comma-separated.
    # Leave empty to always use the direct peer address.
    trusted_proxies: str = ""

    # Database lifecycle
    db_auto_migrate: bool = False

    # RQ queueing / dispatch
    rq_redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "default"
    rq_dispatch_throttle_seconds: float = 15.0
    rq_dispatch_max_retries: int = 3
    # Backoff used when a queue task fails (exponential, capped). 60s base
    # avoids hammering a slow gateway with 10s retries during transport
    # failures (which compounds the load and causes a retry storm).
    rq_dispatch_retry_base_seconds: float = 60.0
    rq_dispatch_retry_max_seconds: float = 600.0

    # Org-level standalone agent reconciliation interval (seconds).
    # Runs reconcile_all_orgs + sweep_stuck_provisioning_agents on this cadence.
    # The sweep auto-recovers agents that got knocked offline by a gateway
    # worker restart (which wipes the in-memory ``agents.list``), so the
    # cadence is also the recovery time after a worker bounce.
    org_agent_reconcile_interval_seconds: int = 300

    # Agent provisioning watchdog: how long (seconds) after a wake call the agent
    # must send its first heartbeat before the reconcile worker retries.
    #
    # Bootstrap is multi-turn: read AGENTS.md → BOOTSTRAP.md → run shell setup
    # → curl /healthz → curl /heartbeat. Each LLM turn is 5–30 s; on NFS-backed
    # sessions an `agents.create` write can stall 30–89 s under contention.
    # The previous 120 s budget guaranteed retries fired mid-bootstrap, before
    # the agent could send its first heartbeat — and combined with session
    # resets on retry, the agent never made progress. 600 s gives realistic
    # headroom while still catching genuinely-dead agents within OFFLINE_AFTER.
    agent_checkin_deadline_seconds: int = 600

    # Maximum number of wake retries before the reconciler gives up and marks
    # the agent offline.
    agent_max_wake_attempts: int = 5

    # Age (seconds) beyond which an agent stuck in 'provisioning' with no
    # heartbeat is treated as orphaned and re-enqueued for a retry.  This sweep
    # runs inside the periodic org-agent reconcile cycle and catches agents that
    # were provisioned before the enqueue-on-failure fix was deployed.
    #
    # Aligned with the checkin deadline above: the sweep should not fire faster
    # than the lifecycle's own retry budget, otherwise the org sweep races the
    # lifecycle reconcile and we get duplicate enqueues during bootstrap.
    agent_stuck_provisioning_sweep_seconds: int = 900

    # OpenClaw gateway runtime compatibility
    gateway_min_version: str = "2026.02.9"

    # Feature flags
    channels_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("CHANNELS_ENABLED", "channels_enabled"),
    )
    planning_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("PLANNING_ENABLED", "planning_enabled"),
    )
    # Optional org-wide standalone agents that the graduation workflow dispatches
    # to. When set, plan decomposition / backlog estimation / backlog
    # prioritisation routes to these agents instead of the board lead.
    org_planner_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices("ORG_PLANNER_AGENT_ID", "org_planner_agent_id"),
    )
    # The triager decomposes plans into backlog tickets; the planner does
    # sprint composition / prioritisation / velocity (its template
    # explicitly says creating tickets is the triager's job). The
    # decompose dispatch path uses this agent when
    # plan.decomposition_target == "org_triager".
    org_triager_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices("ORG_TRIAGER_AGENT_ID", "org_triager_agent_id"),
    )
    org_estimator_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices("ORG_ESTIMATOR_AGENT_ID", "org_estimator_agent_id"),
    )
    org_prioritiser_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices("ORG_PRIORITISER_AGENT_ID", "org_prioritiser_agent_id"),
    )
    # Review agents dispatched at sprint review time (graduation gate).
    org_qa_reviewer_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices("ORG_QA_REVIEWER_AGENT_ID", "org_qa_reviewer_agent_id"),
    )
    org_security_reviewer_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ORG_SECURITY_REVIEWER_AGENT_ID", "org_security_reviewer_agent_id"
        ),
    )
    org_architecture_reviewer_agent_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ORG_ARCHITECTURE_REVIEWER_AGENT_ID", "org_architecture_reviewer_agent_id"
        ),
    )
    sprint_review_pending_retry_minutes: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "SPRINT_REVIEW_PENDING_RETRY_MINUTES",
            "sprint_review_pending_retry_minutes",
        ),
    )
    agent_model_routing: str = Field(
        default="",
        validation_alias=AliasChoices("AXIACRAFT_AGENT_MODEL_ROUTING", "agent_model_routing"),
    )

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"
    log_use_utc: bool = False
    request_log_slow_ms: int = Field(default=1000, ge=0)
    request_log_include_health: bool = False

    @model_validator(mode="after")
    def _defaults(self) -> Self:
        if self.auth_mode == AuthMode.CLERK:
            if not self.clerk_secret_key.strip():
                raise ValueError(
                    "CLERK_SECRET_KEY must be set and non-empty when AUTH_MODE=clerk.",
                )
        elif self.auth_mode == AuthMode.LOCAL:
            token = self.local_auth_token.strip()
            if (
                not token
                or len(token) < LOCAL_AUTH_TOKEN_MIN_LENGTH
                or token.lower() in LOCAL_AUTH_TOKEN_PLACEHOLDERS
            ):
                raise ValueError(
                    "LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local.",
                )

        base_url = self.base_url.strip()
        if not base_url:
            raise ValueError("BASE_URL must be set and non-empty.")
        parsed_base_url = urlparse(base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError(
                "BASE_URL must be an absolute http(s) URL (e.g. http://localhost:8000).",
            )
        self.base_url = base_url.rstrip("/")

        # Rate-limit: fall back to rq_redis_url if using redis backend
        # with no explicit rate-limit URL. If both are blank, fail fast
        # with a clear configuration error.
        if (
            self.rate_limit_backend == RateLimitBackend.REDIS
            and not self.rate_limit_redis_url.strip()
        ):
            fallback_url = self.rq_redis_url.strip()
            if not fallback_url:
                raise ValueError(
                    "RATE_LIMIT_REDIS_URL or RQ_REDIS_URL must be set and non-empty "
                    "when RATE_LIMIT_BACKEND=redis.",
                )
            self.rate_limit_redis_url = fallback_url

        # In dev, default to applying Alembic migrations at startup to avoid
        # schema drift (e.g. missing newly-added columns).
        if "db_auto_migrate" not in self.model_fields_set and self.environment == "dev":
            self.db_auto_migrate = True
        return self


settings = Settings()

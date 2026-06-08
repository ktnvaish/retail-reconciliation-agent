"""Application configuration.

Two distinct sources, kept deliberately separate:

* :class:`AppSettings` — *secrets and environment*: API keys, the chosen
  notifier, file paths, ports. Loaded from environment variables / ``.env``.
* :class:`AppConfig` — *non-secret business configuration*: recipient addresses,
  tolerances, SLA windows, planner allow-list. Loaded from
  ``config/settings.yaml`` (safe to commit).

Recipient addresses may be overridden per-deployment via ``RECIPIENT_*``
environment variables (precedence: env > YAML), so real inboxes never need to be
committed to a public repository.
"""

from __future__ import annotations

import functools
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from reconcile.models.domain import (
    PaymentGateway,
    PaymentType,
    PlannerAction,
    RecipientRole,
)

NotifierName = Literal["resend", "smtp", "mock"]


# --------------------------------------------------------------------------- #
# Environment settings (secrets + runtime)
# --------------------------------------------------------------------------- #


class AppSettings(BaseSettings):
    """Secrets and runtime settings sourced from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    mock_llm: bool = True
    max_llm_calls: int = 200

    # Notifier
    notifier: NotifierName = "mock"

    # Resend
    resend_api_key: str = ""
    resend_from: str = "alerts@example.com"

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # Application
    data_dir: Path = Path("data/runtime")
    database_url: str = "sqlite:///data/runtime/reconcile.db"
    log_level: str = "INFO"
    port: int = 8000
    config_path: Path = Path("config/settings.yaml")

    # Hosted-demo hardening
    demo_access_key: str = ""

    # Recipient overrides (precedence over YAML when non-empty)
    recipient_store_manager: str = ""
    recipient_admin: str = ""
    recipient_bank: str = ""
    recipient_pg_razorpay: str = ""
    recipient_pg_payu: str = ""
    recipient_pg_cashfree: str = ""

    # Tracing (optional)
    langsmith_api_key: str = ""
    langsmith_project: str = "reconcileflow"
    langsmith_tracing: bool = False

    @property
    def incidents_dir(self) -> Path:
        """Directory for incident JSON files and ``incidents.jsonl``."""
        return self.data_dir / "incidents"

    @property
    def mock_outbox_path(self) -> Path:
        """Path to the mock notifier's append-only outbox."""
        return self.data_dir / "mock_outbox.jsonl"


# --------------------------------------------------------------------------- #
# YAML business configuration
# --------------------------------------------------------------------------- #


class RecipientsConfig(BaseModel):
    """Stakeholder email addresses by role."""

    model_config = ConfigDict(extra="forbid")

    store_manager: str
    admin: str
    bank: str
    payment_gateways: dict[PaymentGateway, str]

    def for_gateway(self, gateway: PaymentGateway) -> str:
        """Email for a specific gateway, falling back to the admin address."""
        return self.payment_gateways.get(gateway, self.admin)

    def for_role(self, role: RecipientRole, gateway: PaymentGateway | None = None) -> str:
        """Resolve the email address for a role (gateway-aware for PG)."""
        match role:
            case RecipientRole.STORE_MANAGER:
                return self.store_manager
            case RecipientRole.BANK:
                return self.bank
            case RecipientRole.ADMIN:
                return self.admin
            case RecipientRole.PAYMENT_GATEWAY:
                if gateway is not None:
                    return self.for_gateway(gateway)
                return self.admin


class ReconciliationConfig(BaseModel):
    """Tolerances and SLA windows for matching."""

    model_config = ConfigDict(extra="forbid")

    amount_tolerance: Decimal = Decimal("1.00")
    sla_grace_days: dict[PaymentType, int] = Field(default_factory=dict)


class PlannerConfig(BaseModel):
    """Planner allow-list and the deterministic off-list fallback."""

    model_config = ConfigDict(extra="forbid")

    allowed_actions: list[PlannerAction]
    off_list_fallback: PlannerAction = PlannerAction.ESCALATE


class FuzzyMatchConfig(BaseModel):
    """Confidence thresholds for the LLM fuzzy-matching step."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    auto_apply_threshold: float = 0.85
    review_threshold: float = 0.50


class ResilienceConfig(BaseModel):
    """Retry and circuit-breaker tuning."""

    model_config = ConfigDict(extra="forbid")

    email_retry_attempts: int = 3
    email_retry_min_seconds: float = 1.0
    email_retry_max_seconds: float = 8.0
    circuit_breaker_fail_max: int = 3
    circuit_breaker_reset_seconds: int = 30


class IncidentsConfig(BaseModel):
    """Incident persistence and admin-notification behavior."""

    model_config = ConfigDict(extra="forbid")

    dirname: str = "incidents"
    admin_email_best_effort: bool = True


class AppConfig(BaseModel):
    """Root non-secret business configuration loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    recipients: RecipientsConfig
    reconciliation: ReconciliationConfig = Field(default_factory=ReconciliationConfig)
    planner: PlannerConfig
    fuzzy_match: FuzzyMatchConfig = Field(default_factory=FuzzyMatchConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    incidents: IncidentsConfig = Field(default_factory=IncidentsConfig)


# --------------------------------------------------------------------------- #
# Loading + recipient resolution
# --------------------------------------------------------------------------- #


def _apply_recipient_overrides(
    recipients: RecipientsConfig, settings: AppSettings
) -> RecipientsConfig:
    """Return a copy of ``recipients`` with non-empty ``RECIPIENT_*`` env overrides applied."""
    gateways = dict(recipients.payment_gateways)
    if settings.recipient_pg_razorpay:
        gateways[PaymentGateway.RAZORPAY] = settings.recipient_pg_razorpay
    if settings.recipient_pg_payu:
        gateways[PaymentGateway.PAYU] = settings.recipient_pg_payu
    if settings.recipient_pg_cashfree:
        gateways[PaymentGateway.CASHFREE] = settings.recipient_pg_cashfree

    return recipients.model_copy(
        update={
            "store_manager": settings.recipient_store_manager or recipients.store_manager,
            "admin": settings.recipient_admin or recipients.admin,
            "bank": settings.recipient_bank or recipients.bank,
            "payment_gateways": gateways,
        }
    )


def load_app_config(settings: AppSettings) -> AppConfig:
    """Load and validate the YAML business config, applying recipient overrides."""
    path = settings.config_path
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = AppConfig.model_validate(raw)
    resolved = _apply_recipient_overrides(config.recipients, settings)
    return config.model_copy(update={"recipients": resolved})


@functools.lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return process-wide application settings (cached)."""
    return AppSettings()

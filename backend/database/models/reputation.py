from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.connection import Base


class ReputationSnapshot(Base):
    """
    Stocke le score de réputation d'une organisation
    pour une période précise.

    Exemple :
    ARMA, semaine du 27 avril au 3 mai, score 78/100.
    """

    __tablename__ = "reputation_snapshots"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "period_start",
            "period_end",
            "formula_version",
            name="uq_reputation_snapshot_period",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "pipeline_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    period_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    period_end: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    period_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="weekly",
        server_default="weekly",
    )

    reputation_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    mention_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    positive_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    neutral_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    negative_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    positive_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    negative_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    delta_previous_period: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    dominant_topic_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "topics.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    analyst_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    formula_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="v1",
        server_default="v1",
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class Alert(Base):
    """
    Stocke une mention nécessitant une intervention.

    Exemple :
    plainte concernant un retard de collecte à Casablanca.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    mention_organization_id: Mapped[int] = mapped_column(
        ForeignKey(
            "mention_organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    alert_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        server_default="medium",
        index=True,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="open",
        server_default="open",
        index=True,
    )

    assigned_to: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # En Python : extra_data
    # Dans PostgreSQL : colonne nommée metadata
    extra_data: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class ResponseDraft(Base):
    """
    Stocke une réponse bilingue générée pour une alerte.

    Exemple :
    {
        "fr": "Bonjour, nous sommes désolés...",
        "ar": "السلام عليكم، نعتذر..."
    }
    """

    __tablename__ = "response_drafts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    alert_id: Mapped[int] = mapped_column(
        ForeignKey(
            "alerts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "pipeline_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    content_by_language: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    tone: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )

    model_provider: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    external_response_id: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    # En Python : extra_data
    # Dans PostgreSQL : colonne nommée metadata
    extra_data: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class FacebookReplyAudit(Base):
    """Audit immuable d'une demande de réponse Meta, jamais d'envoi automatique."""

    __tablename__ = "facebook_reply_audits"
    __table_args__ = (UniqueConstraint("mention_id", "platform_response_id", name="uq_fb_reply_platform_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mention_id: Mapped[int] = mapped_column(ForeignKey("mentions.id", ondelete="CASCADE"), nullable=False, index=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", server_default="draft", index=True)
    human_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sql_text("false"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    platform_response_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    api_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb"))

from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class MentionAnalysis(Base):
    """
    Stocke le résultat de l'analyse NLP d'une mention
    pour une organisation précise.

    Exemple :
    une même publication peut être positive pour ARMA
    et négative pour OZONE.
    """

    __tablename__ = "mention_analyses"

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

    model_provider: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    model_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    sentiment_label: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    positive_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    neutral_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    negative_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    analysis_language: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )

    analyzed_at: Mapped[datetime] = mapped_column(
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


class Topic(Base):
    """
    Référentiel des thèmes détectés dans les mentions.

    Exemples :
    retard de collecte, recyclage, réglementation,
    propreté urbaine, réclamation citoyenne.
    """

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        unique=True,
    )

    slug: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        unique=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MentionTopic(Base):
    """
    Associe une mention à un ou plusieurs thèmes.
    """

    __tablename__ = "mention_topics"

    __table_args__ = (
        UniqueConstraint(
            "mention_id",
            "topic_id",
            name="uq_mention_topic",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    mention_id: Mapped[int] = mapped_column(
        ForeignKey(
            "mentions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    topic_id: Mapped[int] = mapped_column(
        ForeignKey(
            "topics.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sql_text("false"),
    )

    detection_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="llm",
        server_default="llm",
    )
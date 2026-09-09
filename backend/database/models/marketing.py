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


class BusinessMetric(Base):
    """
    Stocke les indicateurs internes réels d'ARMA.

    Exemples :
    - taux de pointage ;
    - kilomètres parcourus ;
    - litres de gasoil ;
    - tonnes de déchets collectées ;
    - trésorerie.
    """

    __tablename__ = "business_metrics"

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

    metric_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    metric_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    numeric_value: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    text_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    period_start: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    period_end: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    source_system: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    is_validated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sql_text("false"),
    )

    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    validated_by: Mapped[str | None] = mapped_column(
        String(200),
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


class StrategicAngle(Base):
    """
    Stocke un angle stratégique proposé par l'agent stratège.

    Exemples :
    - Stabilité et performance ;
    - Performance par les chiffres ;
    - Ancrage marocain durable ;
    - Partenariat public-privé.
    """

    __tablename__ = "strategic_angles"

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

    title: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    rationale: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    priority_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="proposed",
        server_default="proposed",
        index=True,
    )

    target_platforms: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
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

    # Peut contenir les identifiants des actualités et KPI
    # utilisés par l'agent pour proposer cet angle.
    extra_data: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class GeneratedPost(Base):
    """
    Stocke une publication générée pour une plateforme.

    Une publication contient les versions française et arabe,
    le prompt d'image et son état de validation.
    """

    __tablename__ = "generated_posts"

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

    strategic_angle_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "strategic_angles.id",
            ondelete="SET NULL",
        ),
        nullable=True,
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

    display_order: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    platform: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    
   # Exemple de contenu JSON :

   # {
   #     "fr": {
   #        "body": "Une semaine après Earth Day...",
    #        "hashtags": ["#ARMA", "#Environnement"]
    #    },
      #  "ar": {
       #     "body": "بعد أسبوع من يوم الأرض...",
       #     "hashtags": ["#أرما", "#البيئة"]
     #   }
   # }
    
    content_by_language: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    image_prompt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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

    reviewed_by: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    external_publication_id: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    extra_data: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class PostEvidenceMention(Base):
    """
    Relie une publication générée aux actualités ou mentions
    qui ont servi de preuves pour sa rédaction.
    """

    __tablename__ = "post_evidence_mentions"

    __table_args__ = (
        UniqueConstraint(
            "generated_post_id",
            "mention_id",
            name="uq_post_evidence_mention",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    generated_post_id: Mapped[int] = mapped_column(
        ForeignKey(
            "generated_posts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    mention_id: Mapped[int] = mapped_column(
        ForeignKey(
            "mentions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    relevance_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    evidence_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PostEvidenceMetric(Base):
    """
    Relie une publication générée aux indicateurs internes
    d'ARMA utilisés dans son contenu.
    """

    __tablename__ = "post_evidence_metrics"

    __table_args__ = (
        UniqueConstraint(
            "generated_post_id",
            "business_metric_id",
            name="uq_post_evidence_metric",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    generated_post_id: Mapped[int] = mapped_column(
        ForeignKey(
            "generated_posts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    business_metric_id: Mapped[int] = mapped_column(
        ForeignKey(
            "business_metrics.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    relevance_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    evidence_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
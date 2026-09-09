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


class PipelineRun(Base):
    """
    Enregistre chaque exécution du pipeline.
    Exemple : une collecte Serper lancée aujourd'hui.
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    run_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    )

    watch_query_id: Mapped[int | None] = mapped_column(
        ForeignKey("watch_queries.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="running",
        server_default="running",
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    items_received: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    items_created: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    items_duplicated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    statistics: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )


class Mention(Base):
    """
    Stocke un article, un post, un commentaire
    ou un résultat trouvé sur Internet.
    """

    __tablename__ = "mentions"

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_mention_source_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Type explicite du contenu. Les anciennes lignes gardent
    # la valeur générique "mention" ; les nouvelles collectes
    # utilisent notamment "social_post" et "social_comment".
    content_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="mention",
        server_default="mention",
        index=True,
    )

    # Métadonnées de qualification pour la vue Marketing Contenu.
    # Elles empêchent les profils, recrutements et posts génériques de
    # polluer la veille affichée au métier.
    business_category: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        index=True,
    )

    business_relevance_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        index=True,
    )

    business_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    display_in_marketing: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sql_text("false"),
        index=True,
    )

    quality_flags: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sql_text("'[]'::jsonb"),
    )

    # Pour un commentaire, pointe vers le post Facebook parent.
    # Cette relation permet de retrouver facilement tous les
    # commentaires associés à une publication collectée.
    parent_mention_id: Mapped[int | None] = mapped_column(
        ForeignKey("mentions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    pipeline_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    external_id: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    title: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    clean_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    author_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    author_handle: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_at_confidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    published_at_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown", server_default="unknown"
    )
    display_title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    display_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_title_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    route_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    validation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending", index=True
    )
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manual_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manual_route: Mapped[str | None] = mapped_column(String(50), nullable=True)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    detected_language: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    country: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )

    engagement: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )

    raw_payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
    )

    processing_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="new",
        server_default="new",
    )


class MentionOrganization(Base):
    """
    Indique quelles entreprises sont citées
    dans une mention.
    """

    __tablename__ = "mention_organizations"

    __table_args__ = (
        UniqueConstraint(
            "mention_id",
            "organization_id",
            name="uq_mention_organization",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    mention_id: Mapped[int] = mapped_column(
        ForeignKey("mentions.id", ondelete="CASCADE"),
        nullable=False,
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    relevance_score: Mapped[float | None] = mapped_column(
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
        String(30),
        nullable=False,
        default="alias_matching",
        server_default="alias_matching",
    )

    # Permet d'exclure du sentiment et du score les contenus
    # éditoriaux de l'entreprise (owned), tout en gardant les
    # avis externes et les commentaires des internautes.
    include_in_reputation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sql_text("true"),
        index=True,
    )

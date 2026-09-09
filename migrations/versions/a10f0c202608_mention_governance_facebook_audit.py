"""mention governance and Facebook reply audit

Revision ID: a10f0c202608
Revises: 91c2f4a0b7de
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a10f0c202608"
down_revision: Union[str, None] = "91c2f4a0b7de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("published_at_confidence", sa.String(20), nullable=False, server_default="unknown"))
    op.add_column("mentions", sa.Column("published_at_source", sa.String(30), nullable=False, server_default="unknown"))
    op.add_column("mentions", sa.Column("display_title", sa.String(1000), nullable=True))
    op.add_column("mentions", sa.Column("display_excerpt", sa.Text(), nullable=True))
    op.add_column("mentions", sa.Column("display_title_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("mentions", sa.Column("route_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("mentions", sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mentions", sa.Column("validated_by", sa.String(200), nullable=True))
    op.add_column("mentions", sa.Column("validation_status", sa.String(30), nullable=False, server_default="pending"))
    op.add_column("mentions", sa.Column("validation_notes", sa.Text(), nullable=True))
    op.add_column("mentions", sa.Column("manual_published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("mentions", sa.Column("manual_category", sa.String(50), nullable=True))
    op.add_column("mentions", sa.Column("manual_route", sa.String(50), nullable=True))
    op.create_index("ix_mentions_validation_status", "mentions", ["validation_status"])
    op.create_table(
        "facebook_reply_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mention_id", sa.Integer(), sa.ForeignKey("mentions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("human_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(200), nullable=True),
        sa.Column("platform_response_id", sa.String(300), nullable=True),
        sa.Column("api_error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("mention_id", "platform_response_id", name="uq_fb_reply_platform_id"),
    )
    op.create_index("ix_facebook_reply_audits_mention_id", "facebook_reply_audits", ["mention_id"])
    op.create_index("ix_facebook_reply_audits_status", "facebook_reply_audits", ["status"])


def downgrade() -> None:
    op.drop_table("facebook_reply_audits")
    op.drop_index("ix_mentions_validation_status", table_name="mentions")
    for column in ("manual_route", "manual_category", "manual_published_at", "validation_notes", "validation_status", "validated_by", "validated_at", "route_metadata", "display_title_generated", "display_excerpt", "display_title", "published_at_source", "published_at_confidence"):
        op.drop_column("mentions", column)

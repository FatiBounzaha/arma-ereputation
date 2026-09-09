"""business relevance fields

Revision ID: 91c2f4a0b7de
Revises: 4b8c1f2d9a01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "91c2f4a0b7de"
down_revision: Union[str, None] = "4b8c1f2d9a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("business_category", sa.String(length=40), nullable=True))
    op.add_column("mentions", sa.Column("business_relevance_score", sa.Float(), nullable=True))
    op.add_column("mentions", sa.Column("business_summary", sa.Text(), nullable=True))
    op.add_column(
        "mentions",
        sa.Column("display_in_marketing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "mentions",
        sa.Column(
            "quality_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_mentions_business_category"), "mentions", ["business_category"], unique=False)
    op.create_index(op.f("ix_mentions_business_relevance_score"), "mentions", ["business_relevance_score"], unique=False)
    op.create_index(op.f("ix_mentions_display_in_marketing"), "mentions", ["display_in_marketing"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_mentions_display_in_marketing"), table_name="mentions")
    op.drop_index(op.f("ix_mentions_business_relevance_score"), table_name="mentions")
    op.drop_index(op.f("ix_mentions_business_category"), table_name="mentions")
    op.drop_column("mentions", "quality_flags")
    op.drop_column("mentions", "display_in_marketing")
    op.drop_column("mentions", "business_summary")
    op.drop_column("mentions", "business_relevance_score")
    op.drop_column("mentions", "business_category")

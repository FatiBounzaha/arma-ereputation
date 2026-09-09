"""social comments and reputation filter

Revision ID: 4b8c1f2d9a01
Revises: deedc3b93eb7
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b8c1f2d9a01"
down_revision: Union[str, Sequence[str], None] = "deedc3b93eb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mentions",
        sa.Column(
            "content_type",
            sa.String(length=30),
            server_default="mention",
            nullable=False,
        ),
    )
    op.add_column(
        "mentions",
        sa.Column("parent_mention_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_mentions_parent_mention_id_mentions",
        "mentions",
        "mentions",
        ["parent_mention_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_mentions_content_type",
        "mentions",
        ["content_type"],
        unique=False,
    )
    op.create_index(
        "ix_mentions_parent_mention_id",
        "mentions",
        ["parent_mention_id"],
        unique=False,
    )

    op.add_column(
        "mention_organizations",
        sa.Column(
            "include_in_reputation",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_mention_organizations_include_in_reputation",
        "mention_organizations",
        ["include_in_reputation"],
        unique=False,
    )

    # Reprend la décision déjà stockée dans raw_payload pour les
    # publications sociales créées avant cette migration.
    op.execute(
        """
        UPDATE mention_organizations AS mo
        SET include_in_reputation = CASE
            WHEN m.raw_payload -> '_collection' ->> 'include_in_reputation'
                 IN ('true', 'false')
            THEN (m.raw_payload -> '_collection' ->> 'include_in_reputation')::boolean
            ELSE true
        END
        FROM mentions AS m
        WHERE m.id = mo.mention_id
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mention_organizations_include_in_reputation",
        table_name="mention_organizations",
    )
    op.drop_column("mention_organizations", "include_in_reputation")

    op.drop_index("ix_mentions_parent_mention_id", table_name="mentions")
    op.drop_index("ix_mentions_content_type", table_name="mentions")
    op.drop_constraint(
        "fk_mentions_parent_mention_id_mentions",
        "mentions",
        type_="foreignkey",
    )
    op.drop_column("mentions", "parent_mention_id")
    op.drop_column("mentions", "content_type")

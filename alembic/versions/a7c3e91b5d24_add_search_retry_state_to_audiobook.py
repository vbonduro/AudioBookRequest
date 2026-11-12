"""add search retry state and downloaded file to audiobook

Revision ID: a7c3e91b5d24
Revises: f1a2b3c4d5e6
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e91b5d24"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audiobook", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "search_attempts", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column("next_search_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("downloaded_file", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audiobook", schema=None) as batch_op:
        batch_op.drop_column("downloaded_file")
        batch_op.drop_column("next_search_at")
        batch_op.drop_column("search_attempts")

"""alternative offers

Revision ID: aa6101b453e5
Revises: 7bd2f0b24507
Create Date: 2026-10-23 01:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "aa6101b453e5"
down_revision: str | None = "7bd2f0b24507"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "credit_memos",
        sa.Column(
            "alternative_offers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.alter_column("credit_memos", "alternative_offers", server_default=None)


def downgrade() -> None:
    op.drop_column("credit_memos", "alternative_offers")

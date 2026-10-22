"""unique user phone

Revision ID: 443b0e9e8f62
Revises: aa6101b453e5
Create Date: 2026-10-23 01:13:35.068851

"""

from collections.abc import Sequence

from alembic import op

revision: str = "443b0e9e8f62"
down_revision: str | None = "aa6101b453e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_users_phone"), "users", ["phone"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_users_phone"), "users", type_="unique")

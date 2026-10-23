"""analyst recommendation

Revision ID: 7bd2f0b24507
Revises: a930574dd197
Create Date: 2026-10-21 18:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7bd2f0b24507"
down_revision: str | None = "a930574dd197"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECOMMENDATIONS = ("approve", "counter_offer", "decline", "request_more_info")


def upgrade() -> None:
    op.add_column(
        "credit_memos", sa.Column("analyst_recommendation", sa.String(length=32), nullable=True)
    )
    # CHECK для varchar-enum autogenerate не создаёт
    values = ", ".join(repr(v) for v in RECOMMENDATIONS)
    op.create_check_constraint(
        op.f("ck_credit_memos_analyst_recommendation"),
        "credit_memos",
        f"analyst_recommendation IN ({values})",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_credit_memos_analyst_recommendation"), "credit_memos", type_="check"
    )
    op.drop_column("credit_memos", "analyst_recommendation")

"""compliance check source

Revision ID: c9fbe46d805c
Revises: 443b0e9e8f62
Create Date: 2026-10-23 21:41:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9fbe46d805c"
down_revision: str | None = "443b0e9e8f62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("egrul", "fns", "bki", "fssp", "bank_turnover", "digital_profile")
NEW = (*OLD, "compliance")


def _recreate(values: tuple[str, ...]) -> None:
    # CHECK для varchar-enum autogenerate не сравнивает - пересоздаём вручную
    op.drop_constraint(op.f("ck_external_checks_checksource"), "external_checks", type_="check")
    op.create_check_constraint(
        op.f("ck_external_checks_checksource"),
        "external_checks",
        f"source IN ({', '.join(repr(v) for v in values)})",
    )


def upgrade() -> None:
    _recreate(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM external_checks WHERE source = 'compliance'")
    _recreate(OLD)

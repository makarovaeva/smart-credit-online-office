"""credit policy counter offers

Revision ID: a930574dd197
Revises: 3848f9947e83
Create Date: 2026-10-21 17:53:22.086883

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a930574dd197"
down_revision: str | None = "3848f9947e83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CHECK для varchar-enum autogenerate не сравнивает - пересоздаём вручную
OLD_DOCUMENT_TYPES = (
    "bank_statement",
    "tax_return",
    "kudir",
    "financial_statement",
    "management_report",
    "contract",
    "collateral",
    "credit_agreement",
    "other",
)
NEW_DOCUMENT_TYPES = (
    "bank_statement",
    "tax_return",
    "kudir",
    "financial_statement",
    "management_report",
    "contract",
    "egrn_extract",
    "vehicle_passport",
    "equipment_documents",
    "appraisal_report",
    "credit_agreement",
    "other",
)
CLOSE_REASONS = ("pre_approval_declined", "auto_declined", "underwriter_declined", "offer_rejected")
MORE_INFO_TARGETS = ("client", "credit_analyst")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("applications", sa.Column("collateral_address", sa.Text(), nullable=True))
    op.add_column("applications", sa.Column("collateral_encumbrances", sa.Text(), nullable=True))
    # Прежние значения были произвольной строкой - сбрасываем всё, чего нет в новом enum
    known = _in("close_reason", CLOSE_REASONS)
    op.execute(f"UPDATE applications SET close_reason = NULL WHERE NOT {known}")
    op.alter_column(
        "applications",
        "close_reason",
        existing_type=sa.VARCHAR(length=50),
        type_=sa.String(length=32),
        existing_nullable=True,
    )
    op.create_check_constraint(
        op.f("ck_applications_closereason"), "applications", _in("close_reason", CLOSE_REASONS)
    )
    op.add_column(
        "credit_decisions", sa.Column("more_info_target", sa.String(length=32), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_credit_decisions_moreinfotarget"),
        "credit_decisions",
        _in("more_info_target", MORE_INFO_TARGETS),
    )
    op.add_column(
        "credit_memos",
        sa.Column(
            "counter_offer_adjustments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.alter_column("credit_memos", "counter_offer_adjustments", server_default=None)
    op.add_column(
        "pre_approvals",
        sa.Column("collateral_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("pre_approvals", "collateral_required", server_default=None)

    op.drop_constraint(op.f("ck_documents_documenttype"), "documents", type_="check")
    op.execute("UPDATE documents SET type = 'other' WHERE type = 'collateral'")
    op.create_check_constraint(
        op.f("ck_documents_documenttype"), "documents", _in("type", NEW_DOCUMENT_TYPES)
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_documents_documenttype"), "documents", type_="check")
    op.execute(
        "UPDATE documents SET type = 'collateral' "
        "WHERE type IN ('egrn_extract', 'vehicle_passport', 'equipment_documents', "
        "'appraisal_report')"
    )
    op.create_check_constraint(
        op.f("ck_documents_documenttype"), "documents", _in("type", OLD_DOCUMENT_TYPES)
    )
    op.drop_column("pre_approvals", "collateral_required")
    op.drop_column("credit_memos", "counter_offer_adjustments")
    op.drop_constraint(
        op.f("ck_credit_decisions_moreinfotarget"), "credit_decisions", type_="check"
    )
    op.drop_column("credit_decisions", "more_info_target")
    op.drop_constraint(op.f("ck_applications_closereason"), "applications", type_="check")
    op.alter_column(
        "applications",
        "close_reason",
        existing_type=sa.String(length=32),
        type_=sa.VARCHAR(length=50),
        existing_nullable=True,
    )
    op.drop_column("applications", "collateral_encumbrances")
    op.drop_column("applications", "collateral_address")

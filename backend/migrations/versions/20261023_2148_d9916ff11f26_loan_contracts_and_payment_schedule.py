"""loan contracts and payment schedule

Revision ID: d9916ff11f26
Revises: c9fbe46d805c
Create Date: 2026-10-23 21:48:29.394323

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9916ff11f26"
down_revision: str | None = "c9fbe46d805c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sequence autogenerate не видит - добавлена вручную
    op.execute(sa.schema.CreateSequence(sa.Sequence("contract_number_seq")))
    op.create_table(
        "loan_contracts",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("credit_decision_id", sa.Uuid(), nullable=False),
        sa.Column("contract_number", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "awaiting_signature",
                "signed",
                "active",
                "overdue",
                "closed",
                name="loancontractstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("principal_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("interest_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "repayment_type",
            sa.Enum(
                "annuity",
                "differentiated",
                name="repaymenttype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("monthly_payment", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("first_payment_date", sa.Date(), nullable=False),
        sa.Column("maturity_date", sa.Date(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_id", sa.String(length=64), nullable=True),
        sa.Column("loan_account_number", sa.String(length=20), nullable=True),
        sa.Column("settlement_account_number", sa.String(length=20), nullable=True),
        sa.Column("disbursed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disbursement_transaction_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_loan_contracts_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credit_decision_id"],
            ["credit_decisions.id"],
            name=op.f("fk_loan_contracts_credit_decision_id_credit_decisions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loan_contracts")),
        sa.UniqueConstraint("application_id", name=op.f("uq_loan_contracts_application_id")),
        sa.UniqueConstraint("contract_number", name=op.f("uq_loan_contracts_contract_number")),
        sa.UniqueConstraint(
            "credit_decision_id", name=op.f("uq_loan_contracts_credit_decision_id")
        ),
        sa.UniqueConstraint(
            "loan_account_number", name=op.f("uq_loan_contracts_loan_account_number")
        ),
    )
    op.create_table(
        "payment_schedule_items",
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("installment_no", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("principal_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("interest_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "paid",
                "overdue",
                name="paymentstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["loan_contracts.id"],
            name=op.f("fk_payment_schedule_items_contract_id_loan_contracts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_schedule_items")),
        sa.UniqueConstraint(
            "contract_id", "installment_no", name=op.f("uq_payment_schedule_items_contract_id")
        ),
    )
    op.create_index(
        op.f("ix_payment_schedule_items_contract_id"),
        "payment_schedule_items",
        ["contract_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_payment_schedule_items_contract_id"), table_name="payment_schedule_items"
    )
    op.drop_table("payment_schedule_items")
    op.drop_table("loan_contracts")
    op.execute(sa.schema.DropSequence(sa.Sequence("contract_number_seq")))

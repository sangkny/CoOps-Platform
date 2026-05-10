"""CoOps — 계약/프로세스 보정 + 결재·Lore 테이블

Revision ID: cop001_approval_lore
Revises:
Create Date: 2026-05-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop001_approval_lore"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    names = set(insp.get_table_names())

    if "coops_contracts" not in names:
        op.create_table(
            "coops_contracts",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("contract_number", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("party_a", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("party_b", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("effective_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("contract_number"),
        )
        op.create_index(
            "ix_coops_contracts_contract_number",
            "coops_contracts",
            ["contract_number"],
            unique=True,
        )

    if "coops_processes" not in names:
        op.create_table(
            "coops_processes",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("workflow_json", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
            sa.Column("contract_id", sa.String(length=36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["contract_id"],
                ["coops_contracts.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(sa.text("DROP TABLE IF EXISTS coops_approval_lore CASCADE"))
    op.execute(sa.text("DROP TABLE IF EXISTS coops_approvals CASCADE"))

    op.create_table(
        "coops_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approver_role", sa.String(length=120), nullable=False, server_default="reviewer"),
        sa.Column("assigned_approver_id", sa.String(length=128), nullable=False),
        sa.Column("requester_id", sa.String(length=128), nullable=False),
        sa.Column("request_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("finalized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["contract_id"], ["coops_contracts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coops_approvals_contract_id", "coops_approvals", ["contract_id"])
    op.create_index("ix_coops_approvals_status", "coops_approvals", ["status"])

    op.create_table(
        "coops_approval_lore",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["approval_id"], ["coops_approvals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coops_approval_lore_approval_id", "coops_approval_lore", ["approval_id"])


def downgrade() -> None:
    op.drop_index("ix_coops_approval_lore_approval_id", table_name="coops_approval_lore")
    op.drop_table("coops_approval_lore")
    op.drop_index("ix_coops_approvals_status", table_name="coops_approvals")
    op.drop_index("ix_coops_approvals_contract_id", table_name="coops_approvals")
    op.drop_table("coops_approvals")

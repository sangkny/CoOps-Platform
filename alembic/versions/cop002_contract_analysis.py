"""cop002 — 계약 DEBATE 분석 이력 저장."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop002_contract_analysis"
down_revision: Union[str, None] = "cop001_approval_lore"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coops_contract_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_number", sa.String(length=32), nullable=False),
        sa.Column("debate_output", sa.Text(), nullable=True),
        sa.Column(
            "risk_level",
            sa.String(length=16),
            nullable=False,
            server_default="low",
        ),
        sa.Column(
            "ontology_passed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("ontology_errors_json", sa.Text(), nullable=True),
        sa.Column("lore_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_coops_contract_analyses_contract_number",
        "coops_contract_analyses",
        ["contract_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_coops_contract_analyses_contract_number",
        table_name="coops_contract_analyses",
    )
    op.drop_table("coops_contract_analyses")

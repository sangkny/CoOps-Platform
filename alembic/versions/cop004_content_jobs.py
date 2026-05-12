"""cop004 — 콘텐츠 생성 통합 ``coops_content_jobs`` (Phase 2 → C Week 2, 2026-05-13).

Video / SNS / Investor 3종 콘텐츠를 단일 테이블 (action 으로 구분) 로 저장.
스키마 분기 가능성 발생 시 sidecar 테이블 추가 (현재는 input_json/output_json 으로 흡수).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "cop004_content_jobs"
down_revision: Union[str, None] = "cop003_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coops_content_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("plan_code", sa.String(length=32), nullable=True),
        sa.Column("model_used", sa.String(length=128), nullable=True),
        sa.Column("strategy", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "tokens_estimated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ontology_passed", sa.Boolean(), nullable=True),
        sa.Column("ontology_errors_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_coops_content_jobs_user_id", "coops_content_jobs", ["user_id"]
    )
    op.create_index(
        "ix_coops_content_jobs_action", "coops_content_jobs", ["action"]
    )
    op.create_index(
        "ix_coops_content_jobs_status", "coops_content_jobs", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_coops_content_jobs_status", table_name="coops_content_jobs")
    op.drop_index("ix_coops_content_jobs_action", table_name="coops_content_jobs")
    op.drop_index("ix_coops_content_jobs_user_id", table_name="coops_content_jobs")
    op.drop_table("coops_content_jobs")

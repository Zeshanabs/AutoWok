"""Add research project, source, finding, report, and usage tables.

Revision ID: 20261105_0005
Revises: 20261103_0004
Create Date: 2026-11-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261105_0005"
down_revision: Union[str, None] = "20261103_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("target_audience", sa.String(length=160), nullable=True),
        sa.Column("geographic_scope", sa.String(length=120), nullable=True),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("recency_preference", sa.String(length=80), nullable=True),
        sa.Column("research_depth", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_stage", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PLANNING', 'SEARCHING', 'RETRIEVING', 'ANALYZING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_research_project_status",
        ),
        sa.CheckConstraint(
            "current_stage IN ('PENDING', 'PLANNING', 'SEARCHING', 'RETRIEVING', 'ANALYZING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_research_project_stage",
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_projects_workspace", "research_projects", ["workspace_id"], unique=False)
    op.create_index("ix_research_projects_brand", "research_projects", ["brand_id"], unique=False)
    op.create_index("ix_research_projects_status", "research_projects", ["status"], unique=False)

    op.create_table(
        "research_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_queries_research_id", "research_queries", ["research_id"], unique=False)
    op.create_index("ix_research_queries_status", "research_queries", ["status"], unique=False)

    op.create_table(
        "research_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("extracted_content", sa.Text(), nullable=True),
        sa.Column("publication_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("retrieval_status", sa.String(length=40), nullable=False),
        sa.Column("quality_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_sources_research_id", "research_sources", ["research_id"], unique=False)
    op.create_index("ix_research_sources_domain", "research_sources", ["domain"], unique=False)
    op.create_index("ix_research_sources_retrieval_status", "research_sources", ["retrieval_status"], unique=False)

    op.create_table(
        "research_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("finding_type", sa.String(length=80), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("confidence_label", sa.String(length=40), nullable=False),
        sa.Column("supporting_source_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_findings_research_id", "research_findings", ["research_id"], unique=False)

    op.create_table(
        "research_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=True),
        sa.Column("key_findings", sa.JSON(), nullable=False),
        sa.Column("trends", sa.JSON(), nullable=False),
        sa.Column("opportunities", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("audience_insights", sa.JSON(), nullable=False),
        sa.Column("competitor_insights", sa.JSON(), nullable=False),
        sa.Column("content_angles", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("generated_by_model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["research_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_id"),
    )
    op.create_index("ix_research_reports_research_id", "research_reports", ["research_id"], unique=False)

    op.create_table(
        "research_usage_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("research_id", sa.Uuid(), nullable=False),
        sa.Column("search_provider", sa.String(length=80), nullable=False),
        sa.Column("ai_provider", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("search_requests", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PLANNING', 'SEARCHING', 'RETRIEVING', 'ANALYZING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_research_usage_status",
        ),
        sa.ForeignKeyConstraint(["research_id"], ["research_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_usage_logs_workspace", "research_usage_logs", ["workspace_id"], unique=False)
    op.create_index("ix_research_usage_logs_research_id", "research_usage_logs", ["research_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_research_usage_logs_research_id", table_name="research_usage_logs")
    op.drop_index("ix_research_usage_logs_workspace", table_name="research_usage_logs")
    op.drop_table("research_usage_logs")
    op.drop_index("ix_research_reports_research_id", table_name="research_reports")
    op.drop_table("research_reports")
    op.drop_index("ix_research_findings_research_id", table_name="research_findings")
    op.drop_table("research_findings")
    op.drop_index("ix_research_sources_retrieval_status", table_name="research_sources")
    op.drop_index("ix_research_sources_domain", table_name="research_sources")
    op.drop_index("ix_research_sources_research_id", table_name="research_sources")
    op.drop_table("research_sources")
    op.drop_index("ix_research_queries_status", table_name="research_queries")
    op.drop_index("ix_research_queries_research_id", table_name="research_queries")
    op.drop_table("research_queries")
    op.drop_index("ix_research_projects_status", table_name="research_projects")
    op.drop_index("ix_research_projects_brand", table_name="research_projects")
    op.drop_index("ix_research_projects_workspace", table_name="research_projects")
    op.drop_table("research_projects")

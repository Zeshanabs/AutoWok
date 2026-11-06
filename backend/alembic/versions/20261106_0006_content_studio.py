"""Add content projects, drafts, versions, and approvals.

Revision ID: 20261106_0006
Revises: 20261105_0005
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261106_0006"
down_revision: Union[str, None] = "20261105_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("selected_platforms", sa.JSON(), nullable=False),
        sa.Column("content_pillar", sa.String(length=160), nullable=True),
        sa.Column("target_audience", sa.String(length=200), nullable=True),
        sa.Column("preferred_tone", sa.String(length=80), nullable=True),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("required_phrases", sa.JSON(), nullable=False),
        sa.Column("prohibited_phrases", sa.JSON(), nullable=False),
        sa.Column("cta_requirements", sa.Text(), nullable=True),
        sa.Column("hashtag_preferences", sa.Text(), nullable=True),
        sa.Column("emoji_preferences", sa.Text(), nullable=True),
        sa.Column("desired_length", sa.String(length=40), nullable=True),
        sa.Column("research_report_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["research_report_id"], ["research_reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_projects_workspace_id", "content_projects", ["workspace_id"])
    op.create_index("ix_content_projects_brand_id", "content_projects", ["brand_id"])
    op.create_index("ix_content_projects_created_by", "content_projects", ["created_by"])
    op.create_index("ix_content_projects_research_report_id", "content_projects", ["research_report_id"])
    op.create_index(
        "ix_content_projects_workspace_status", "content_projects", ["workspace_id", "status"]
    )
    op.create_index(
        "ix_content_projects_brand_created", "content_projects", ["brand_id", "created_at"]
    )

    op.create_table(
        "content_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("cta", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("ai_generated", sa.Boolean(), nullable=False),
        sa.Column("version_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["content_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "platform", name="uq_content_draft_project_platform"),
    )
    op.create_index("ix_content_drafts_project_id", "content_drafts", ["project_id"])
    op.create_index(
        "ix_content_drafts_project_status", "content_drafts", ["project_id", "status"]
    )
    op.create_index("ix_content_drafts_platform", "content_drafts", ["project_id", "platform"])

    op.create_table(
        "content_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("cta", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["draft_id"], ["content_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "version_number", name="uq_content_version_draft_number"),
    )
    op.create_index("ix_content_versions_draft_id", "content_versions", ["draft_id"])
    op.create_index(
        "ix_content_versions_draft_number", "content_versions", ["draft_id", "version_number"]
    )

    op.create_table(
        "content_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["content_drafts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["content_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_approvals_project_id", "content_approvals", ["project_id"])
    op.create_index("ix_content_approvals_draft_id", "content_approvals", ["draft_id"])
    op.create_index("ix_content_approvals_reviewed_by", "content_approvals", ["reviewed_by"])
    op.create_index(
        "ix_content_approvals_project_status", "content_approvals", ["project_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_content_approvals_project_status", table_name="content_approvals")
    op.drop_index("ix_content_approvals_reviewed_by", table_name="content_approvals")
    op.drop_index("ix_content_approvals_draft_id", table_name="content_approvals")
    op.drop_index("ix_content_approvals_project_id", table_name="content_approvals")
    op.drop_table("content_approvals")
    op.drop_index("ix_content_versions_draft_number", table_name="content_versions")
    op.drop_index("ix_content_versions_draft_id", table_name="content_versions")
    op.drop_table("content_versions")
    op.drop_index("ix_content_drafts_platform", table_name="content_drafts")
    op.drop_index("ix_content_drafts_project_status", table_name="content_drafts")
    op.drop_index("ix_content_drafts_project_id", table_name="content_drafts")
    op.drop_table("content_drafts")
    op.drop_index("ix_content_projects_brand_created", table_name="content_projects")
    op.drop_index("ix_content_projects_workspace_status", table_name="content_projects")
    op.drop_index("ix_content_projects_research_report_id", table_name="content_projects")
    op.drop_index("ix_content_projects_created_by", table_name="content_projects")
    op.drop_index("ix_content_projects_brand_id", table_name="content_projects")
    op.drop_index("ix_content_projects_workspace_id", table_name="content_projects")
    op.drop_table("content_projects")

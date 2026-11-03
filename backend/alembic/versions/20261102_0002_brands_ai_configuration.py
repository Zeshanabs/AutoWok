"""Add brand profiles and encrypted AI provider configuration.

Revision ID: 20261102_0002
Revises: 20261102_0001
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261102_0002"
down_revision: Union[str, None] = "20261102_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("business_type", sa.String(length=120), nullable=True),
        sa.Column("logo_url", sa.String(length=2048), nullable=True),
        sa.Column("primary_color", sa.String(length=7), nullable=True),
        sa.Column("secondary_color", sa.String(length=7), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_brand_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_brand_workspace_slug"),
    )
    op.create_index("ix_brands_workspace_id", "brands", ["workspace_id"], unique=False)
    op.create_index("ix_brands_created_by", "brands", ["created_by"], unique=False)
    op.create_index(
        "ix_brands_workspace_status", "brands", ["workspace_id", "status"], unique=False
    )

    op.create_table(
        "brand_voices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("tone", sa.String(length=120), nullable=True),
        sa.Column("personality", sa.Text(), nullable=True),
        sa.Column("writing_style", sa.Text(), nullable=True),
        sa.Column("communication_style", sa.Text(), nullable=True),
        sa.Column("vocabulary_preferences", sa.JSON(), nullable=False),
        sa.Column("preferred_phrases", sa.JSON(), nullable=False),
        sa.Column("prohibited_phrases", sa.JSON(), nullable=False),
        sa.Column("language_preferences", sa.JSON(), nullable=False),
        sa.Column("emoji_policy", sa.String(length=24), nullable=True),
        sa.Column("hashtag_policy", sa.String(length=24), nullable=True),
        sa.Column("call_to_action_style", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brand_id"),
    )

    op.create_table(
        "target_audiences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("audience_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("age_range", sa.String(length=40), nullable=True),
        sa.Column("locations", sa.JSON(), nullable=False),
        sa.Column("interests", sa.JSON(), nullable=False),
        sa.Column("pain_points", sa.JSON(), nullable=False),
        sa.Column("goals", sa.JSON(), nullable=False),
        sa.Column("preferred_platforms", sa.JSON(), nullable=False),
        sa.Column("demographics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_target_audiences_brand", "target_audiences", ["brand_id"], unique=False)

    op.create_table(
        "content_pillars",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("suggested_topics", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_pillars_brand_active", "content_pillars", ["brand_id", "is_active"], unique=False
    )

    op.create_table(
        "brand_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("goal_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("target_metric", sa.String(length=120), nullable=True),
        sa.Column("target_value", sa.String(length=120), nullable=True),
        sa.Column("target_period", sa.String(length=80), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_goals_brand_active", "brand_goals", ["brand_id", "is_active"], unique=False)

    op.create_table(
        "brand_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("policy_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("policy_value", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH')", name="ck_brand_policy_severity"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_brand_policies_brand_active", "brand_policies", ["brand_id", "is_active"], unique=False
    )

    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "provider_name IN ('openai', 'anthropic', 'gemini', 'openai_compatible')",
            name="ck_ai_provider_name",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_provider_configs_workspace_id", "ai_provider_configs", ["workspace_id"], unique=False)
    op.create_index("ix_ai_provider_configs_created_by", "ai_provider_configs", ["created_by"], unique=False)
    op.create_index(
        "ix_ai_provider_workspace_active", "ai_provider_configs", ["workspace_id", "is_active"], unique=False
    )
    op.create_index(
        "uq_ai_provider_default_workspace",
        "ai_provider_configs",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_provider_default_workspace", table_name="ai_provider_configs")
    op.drop_index("ix_ai_provider_workspace_active", table_name="ai_provider_configs")
    op.drop_index("ix_ai_provider_configs_created_by", table_name="ai_provider_configs")
    op.drop_index("ix_ai_provider_configs_workspace_id", table_name="ai_provider_configs")
    op.drop_table("ai_provider_configs")
    op.drop_index("ix_brand_policies_brand_active", table_name="brand_policies")
    op.drop_table("brand_policies")
    op.drop_index("ix_brand_goals_brand_active", table_name="brand_goals")
    op.drop_table("brand_goals")
    op.drop_index("ix_content_pillars_brand_active", table_name="content_pillars")
    op.drop_table("content_pillars")
    op.drop_index("ix_target_audiences_brand", table_name="target_audiences")
    op.drop_table("target_audiences")
    op.drop_table("brand_voices")
    op.drop_index("ix_brands_workspace_status", table_name="brands")
    op.drop_index("ix_brands_created_by", table_name="brands")
    op.drop_index("ix_brands_workspace_id", table_name="brands")
    op.drop_table("brands")

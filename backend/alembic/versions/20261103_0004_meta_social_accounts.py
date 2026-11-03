"""Add secure Meta OAuth and social account storage.

Revision ID: 20261103_0004
Revises: 20261103_0003
Create Date: 2026-11-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261103_0004"
down_revision: Union[str, None] = "20261103_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_by", sa.Uuid(), nullable=False),
        sa.Column("meta_user_id", sa.String(length=255), nullable=False),
        sa.Column("encrypted_user_access_token", sa.Text(), nullable=False),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["authorized_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_meta_authorization_workspace_user",
        "meta_authorizations",
        ["workspace_id", "authorized_by"],
        unique=True,
    )

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider = 'meta'", name="ck_oauth_state_provider"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index("ix_oauth_states_expiry", "oauth_states", ["expires_at"], unique=False)

    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("platform_account_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("profile_image_url", sa.String(length=2048), nullable=True),
        sa.Column("account_type", sa.String(length=64), nullable=True),
        sa.Column("parent_account_id", sa.Uuid(), nullable=True),
        sa.Column("connection_status", sa.String(length=32), nullable=False),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("connected_by", sa.Uuid(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "platform IN ('facebook_page', 'instagram')",
            name="ck_social_account_platform",
        ),
        sa.CheckConstraint(
            "connection_status IN ('connected', 'expired', 'revoked', 'error', 'disconnected')",
            name="ck_social_account_connection_status",
        ),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["connected_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_account_id"], ["social_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_social_account_workspace_platform_id",
        "social_accounts",
        ["workspace_id", "platform", "platform_account_id"],
        unique=True,
    )
    op.create_index(
        "ix_social_accounts_workspace_status",
        "social_accounts",
        ["workspace_id", "connection_status"],
        unique=False,
    )

    op.create_table(
        "social_account_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("social_account_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("token_type", sa.String(length=32), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encryption_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["social_account_id"], ["social_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("social_account_id"),
    )


def downgrade() -> None:
    op.drop_table("social_account_credentials")
    op.drop_index("ix_social_accounts_workspace_status", table_name="social_accounts")
    op.drop_index("uq_social_account_workspace_platform_id", table_name="social_accounts")
    op.drop_table("social_accounts")
    op.drop_index("ix_oauth_states_expiry", table_name="oauth_states")
    op.drop_table("oauth_states")
    op.drop_index("uq_meta_authorization_workspace_user", table_name="meta_authorizations")
    op.drop_table("meta_authorizations")

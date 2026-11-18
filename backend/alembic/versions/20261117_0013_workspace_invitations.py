"""Workspace invitations by email.

Adds one table, ``workspace_invitations``. Nothing existing is changed, so the
previous application version keeps working against the new schema, and the
downgrade only removes the new table (pending invitations would be lost).

Revision ID: 20261117_0013
Revises: 20261116_0012
Create Date: 2026-11-17 00:13:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261117_0013'
down_revision = '20261116_0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workspace_invitations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('invited_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('ADMIN', 'MEMBER')", name='ck_workspace_invitation_role'),
        sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(
        'ix_workspace_invitations_workspace_email', 'workspace_invitations', ['workspace_id', 'email'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_workspace_invitations_workspace_email', table_name='workspace_invitations')
    op.drop_table('workspace_invitations')

"""Add scheduled posts, scheduling history, and user timezone preference.

Phase 8: content calendar, scheduling, and the automated publishing queue.

Revision ID: 20261109_0008
Revises: 20261109_0007
Create Date: 2026-11-09 06:41:38.612375

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261109_0008'
down_revision = '20261109_0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('scheduled_posts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('draft_id', sa.Uuid(), nullable=False),
    sa.Column('social_account_id', sa.Uuid(), nullable=False),
    sa.Column('brand_id', sa.Uuid(), nullable=True),
    sa.Column('platform', sa.String(length=40), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('scheduled_local', sa.String(length=19), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('content_version_number', sa.Integer(), nullable=False),
    sa.Column('active_guard', sa.String(length=120), nullable=True),
    sa.Column('publication_id', sa.Uuid(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('queued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('scheduled', 'queued', 'processing', 'published', 'failed', 'cancelled')", name='ck_scheduled_post_status'),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['draft_id'], ['content_drafts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['project_id'], ['content_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['publication_id'], ['content_publications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('active_guard', name='uq_scheduled_post_active_guard')
    )
    op.create_index(op.f('ix_scheduled_posts_brand_id'), 'scheduled_posts', ['brand_id'], unique=False)
    op.create_index(op.f('ix_scheduled_posts_draft_id'), 'scheduled_posts', ['draft_id'], unique=False)
    op.create_index('ix_scheduled_posts_due', 'scheduled_posts', ['status', 'scheduled_at'], unique=False)
    op.create_index(op.f('ix_scheduled_posts_project_id'), 'scheduled_posts', ['project_id'], unique=False)
    op.create_index(op.f('ix_scheduled_posts_publication_id'), 'scheduled_posts', ['publication_id'], unique=False)
    op.create_index(op.f('ix_scheduled_posts_social_account_id'), 'scheduled_posts', ['social_account_id'], unique=False)
    op.create_index(op.f('ix_scheduled_posts_workspace_id'), 'scheduled_posts', ['workspace_id'], unique=False)
    op.create_index('ix_scheduled_posts_workspace_time', 'scheduled_posts', ['workspace_id', 'scheduled_at'], unique=False)
    op.create_table('scheduling_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scheduled_post_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('previous_scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('new_scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('performed_by', sa.Uuid(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['performed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['scheduled_post_id'], ['scheduled_posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_scheduling_history_post_created', 'scheduling_history', ['scheduled_post_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_scheduling_history_scheduled_post_id'), 'scheduling_history', ['scheduled_post_id'], unique=False)
    op.add_column('users', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('timezone')
    op.drop_index(op.f('ix_scheduling_history_scheduled_post_id'), table_name='scheduling_history')
    op.drop_index('ix_scheduling_history_post_created', table_name='scheduling_history')
    op.drop_table('scheduling_history')
    op.drop_index('ix_scheduled_posts_workspace_time', table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_workspace_id'), table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_social_account_id'), table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_publication_id'), table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_project_id'), table_name='scheduled_posts')
    op.drop_index('ix_scheduled_posts_due', table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_draft_id'), table_name='scheduled_posts')
    op.drop_index(op.f('ix_scheduled_posts_brand_id'), table_name='scheduled_posts')
    op.drop_table('scheduled_posts')

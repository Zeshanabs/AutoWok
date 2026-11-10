"""Add analytics snapshots, post analytics, post analytics history, and analytics sync jobs.

Phase 9: social media analytics, performance tracking, and reporting.

Revision ID: 20261110_0009
Revises: 20261109_0008
Create Date: 2026-11-10 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261110_0009'
down_revision = '20261109_0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('analytics_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('brand_id', sa.Uuid(), nullable=True),
    sa.Column('social_account_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('metric_key', sa.String(length=64), nullable=False),
    sa.Column('source_metric', sa.String(length=128), nullable=False),
    sa.Column('period', sa.String(length=16), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('metric_value', sa.Float(), nullable=True),
    sa.Column('metric_unit', sa.String(length=32), nullable=False),
    sa.Column('value_breakdown', sa.JSON(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('api_version', sa.String(length=16), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("platform IN ('facebook_page', 'instagram')", name='ck_analytics_snapshot_platform'),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('social_account_id', 'metric_key', 'period', 'snapshot_date', name='uq_analytics_snapshot_account_metric_day')
    )
    op.create_index('ix_analytics_snapshots_account_metric', 'analytics_snapshots', ['social_account_id', 'metric_key', 'snapshot_date'], unique=False)
    op.create_index(op.f('ix_analytics_snapshots_brand_id'), 'analytics_snapshots', ['brand_id'], unique=False)
    op.create_index(op.f('ix_analytics_snapshots_social_account_id'), 'analytics_snapshots', ['social_account_id'], unique=False)
    op.create_index('ix_analytics_snapshots_workspace_date', 'analytics_snapshots', ['workspace_id', 'snapshot_date'], unique=False)
    op.create_index(op.f('ix_analytics_snapshots_workspace_id'), 'analytics_snapshots', ['workspace_id'], unique=False)

    op.create_table('post_analytics',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('brand_id', sa.Uuid(), nullable=True),
    sa.Column('social_account_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('publication_id', sa.Uuid(), nullable=True),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('draft_id', sa.Uuid(), nullable=True),
    sa.Column('external_post_id', sa.String(length=255), nullable=False),
    sa.Column('permalink', sa.String(length=2048), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('content_format', sa.String(length=40), nullable=True),
    sa.Column('caption_preview', sa.String(length=280), nullable=True),
    sa.Column('thumbnail_url', sa.String(length=2048), nullable=True),
    sa.Column('reach', sa.Integer(), nullable=True),
    sa.Column('views', sa.Integer(), nullable=True),
    sa.Column('engagements', sa.Integer(), nullable=True),
    sa.Column('likes', sa.Integer(), nullable=True),
    sa.Column('reactions', sa.Integer(), nullable=True),
    sa.Column('comments', sa.Integer(), nullable=True),
    sa.Column('shares', sa.Integer(), nullable=True),
    sa.Column('saves', sa.Integer(), nullable=True),
    sa.Column('clicks', sa.Integer(), nullable=True),
    sa.Column('video_views', sa.Integer(), nullable=True),
    sa.Column('raw_metrics', sa.JSON(), nullable=False),
    sa.Column('metric_availability', sa.JSON(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('api_version', sa.String(length=16), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("platform IN ('facebook_page', 'instagram')", name='ck_post_analytics_platform'),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['draft_id'], ['content_drafts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['content_projects.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['publication_id'], ['content_publications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('social_account_id', 'external_post_id', name='uq_post_analytics_account_post')
    )
    op.create_index(op.f('ix_post_analytics_brand_id'), 'post_analytics', ['brand_id'], unique=False)
    op.create_index(op.f('ix_post_analytics_project_id'), 'post_analytics', ['project_id'], unique=False)
    op.create_index('ix_post_analytics_publication', 'post_analytics', ['publication_id'], unique=False)
    op.create_index(op.f('ix_post_analytics_published_at'), 'post_analytics', ['published_at'], unique=False)
    op.create_index(op.f('ix_post_analytics_social_account_id'), 'post_analytics', ['social_account_id'], unique=False)
    op.create_index(op.f('ix_post_analytics_workspace_id'), 'post_analytics', ['workspace_id'], unique=False)
    op.create_index('ix_post_analytics_workspace_published', 'post_analytics', ['workspace_id', 'published_at'], unique=False)

    op.create_table('post_analytics_history',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('post_analytics_id', sa.Uuid(), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('metrics', sa.JSON(), nullable=False),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['post_analytics_id'], ['post_analytics.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_analytics_id', 'snapshot_date', name='uq_post_analytics_history_day')
    )
    op.create_index(op.f('ix_post_analytics_history_post_analytics_id'), 'post_analytics_history', ['post_analytics_id'], unique=False)

    op.create_table('analytics_sync_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('social_account_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('active_guard', sa.String(length=80), nullable=True),
    sa.Column('range_start', sa.Date(), nullable=True),
    sa.Column('range_end', sa.Date(), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=120), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_category', sa.String(length=40), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('records_processed', sa.Integer(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled')", name='ck_analytics_sync_job_status'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('active_guard', name='uq_analytics_sync_job_active_guard')
    )
    op.create_index('ix_analytics_sync_jobs_account_created', 'analytics_sync_jobs', ['social_account_id', 'created_at'], unique=False)
    op.create_index('ix_analytics_sync_jobs_due', 'analytics_sync_jobs', ['status', 'next_attempt_at'], unique=False)
    op.create_index(op.f('ix_analytics_sync_jobs_social_account_id'), 'analytics_sync_jobs', ['social_account_id'], unique=False)
    op.create_index(op.f('ix_analytics_sync_jobs_workspace_id'), 'analytics_sync_jobs', ['workspace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_analytics_sync_jobs_workspace_id'), table_name='analytics_sync_jobs')
    op.drop_index(op.f('ix_analytics_sync_jobs_social_account_id'), table_name='analytics_sync_jobs')
    op.drop_index('ix_analytics_sync_jobs_due', table_name='analytics_sync_jobs')
    op.drop_index('ix_analytics_sync_jobs_account_created', table_name='analytics_sync_jobs')
    op.drop_table('analytics_sync_jobs')
    op.drop_index(op.f('ix_post_analytics_history_post_analytics_id'), table_name='post_analytics_history')
    op.drop_table('post_analytics_history')
    op.drop_index('ix_post_analytics_workspace_published', table_name='post_analytics')
    op.drop_index(op.f('ix_post_analytics_workspace_id'), table_name='post_analytics')
    op.drop_index(op.f('ix_post_analytics_social_account_id'), table_name='post_analytics')
    op.drop_index(op.f('ix_post_analytics_published_at'), table_name='post_analytics')
    op.drop_index('ix_post_analytics_publication', table_name='post_analytics')
    op.drop_index(op.f('ix_post_analytics_project_id'), table_name='post_analytics')
    op.drop_index(op.f('ix_post_analytics_brand_id'), table_name='post_analytics')
    op.drop_table('post_analytics')
    op.drop_index(op.f('ix_analytics_snapshots_workspace_id'), table_name='analytics_snapshots')
    op.drop_index('ix_analytics_snapshots_workspace_date', table_name='analytics_snapshots')
    op.drop_index(op.f('ix_analytics_snapshots_social_account_id'), table_name='analytics_snapshots')
    op.drop_index(op.f('ix_analytics_snapshots_brand_id'), table_name='analytics_snapshots')
    op.drop_index('ix_analytics_snapshots_account_metric', table_name='analytics_snapshots')
    op.drop_table('analytics_snapshots')

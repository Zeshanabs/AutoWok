"""Add media assets, draft media attachments, publishing jobs, and attempts.

Phase 7: media library, platform previews, and controlled publishing.

Revision ID: 20261109_0007
Revises: 20261106_0006
Create Date: 2026-11-09 06:17:51.473697

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261109_0007'
down_revision = '20261106_0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('media_assets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('brand_id', sa.Uuid(), nullable=True),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('metadata_stripped', sa.Boolean(), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('mime_type', sa.String(length=128), nullable=False),
    sa.Column('file_extension', sa.String(length=32), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.Column('checksum', sa.String(length=128), nullable=False),
    sa.Column('thumbnail_key', sa.String(length=512), nullable=True),
    sa.Column('storage_provider', sa.String(length=64), nullable=False),
    sa.Column('processing_status', sa.String(length=32), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('storage_key')
    )
    op.create_index('ix_media_assets_brand', 'media_assets', ['brand_id'], unique=False)
    op.create_index(op.f('ix_media_assets_brand_id'), 'media_assets', ['brand_id'], unique=False)
    op.create_index('ix_media_assets_checksum', 'media_assets', ['workspace_id', 'checksum'], unique=False)
    op.create_index(op.f('ix_media_assets_uploaded_by'), 'media_assets', ['uploaded_by'], unique=False)
    op.create_index('ix_media_assets_workspace_created', 'media_assets', ['workspace_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_media_assets_workspace_id'), 'media_assets', ['workspace_id'], unique=False)
    op.create_table('content_publications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=False),
    sa.Column('active_guard', sa.String(length=120), nullable=True),
    sa.Column('content_version_number', sa.Integer(), nullable=True),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('external_container_id', sa.String(length=255), nullable=True),
    sa.Column('external_child_ids', sa.JSON(), nullable=False),
    sa.Column('permalink', sa.String(length=2048), nullable=True),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('max_attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=120), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_category', sa.String(length=40), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('requires_user_action', sa.Boolean(), nullable=False),
    sa.Column('outcome_uncertain', sa.Boolean(), nullable=False),
    sa.Column('platform_response', sa.JSON(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('draft_id', sa.Uuid(), nullable=True),
    sa.Column('social_account_id', sa.Uuid(), nullable=True),
    sa.Column('platform', sa.String(length=40), nullable=False),
    sa.Column('media_asset_ids', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('external_post_id', sa.String(length=255), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'processing', 'publishing', 'published', 'failed', 'cancelled')", name='ck_content_publication_status'),
    sa.ForeignKeyConstraint(['draft_id'], ['content_drafts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['content_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('active_guard', name='uq_content_publication_active_guard'),
    sa.UniqueConstraint('workspace_id', 'idempotency_key', name='uq_content_publication_idempotency')
    )
    op.create_index('ix_content_publications_account', 'content_publications', ['social_account_id'], unique=False)
    op.create_index(op.f('ix_content_publications_draft_id'), 'content_publications', ['draft_id'], unique=False)
    op.create_index('ix_content_publications_due', 'content_publications', ['status', 'next_attempt_at'], unique=False)
    op.create_index(op.f('ix_content_publications_project_id'), 'content_publications', ['project_id'], unique=False)
    op.create_index('ix_content_publications_project_status', 'content_publications', ['project_id', 'status'], unique=False)
    op.create_index(op.f('ix_content_publications_social_account_id'), 'content_publications', ['social_account_id'], unique=False)
    op.create_index('ix_content_publications_workspace_created', 'content_publications', ['workspace_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_content_publications_workspace_id'), 'content_publications', ['workspace_id'], unique=False)
    op.create_table('publishing_attempts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('publication_id', sa.Uuid(), nullable=False),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('worker_id', sa.String(length=120), nullable=True),
    sa.Column('error_category', sa.String(length=40), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('retryable', sa.Boolean(), nullable=False),
    sa.Column('response_summary', sa.JSON(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['publication_id'], ['content_publications.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('publication_id', 'attempt_number', name='uq_publishing_attempt_number')
    )
    op.create_index(op.f('ix_publishing_attempts_publication_id'), 'publishing_attempts', ['publication_id'], unique=False)
    op.add_column('content_drafts', sa.Column('media_asset_ids', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade() -> None:
    with op.batch_alter_table('content_drafts') as batch_op:
        batch_op.drop_column('media_asset_ids')
    op.drop_index(op.f('ix_publishing_attempts_publication_id'), table_name='publishing_attempts')
    op.drop_table('publishing_attempts')
    op.drop_index(op.f('ix_content_publications_workspace_id'), table_name='content_publications')
    op.drop_index('ix_content_publications_workspace_created', table_name='content_publications')
    op.drop_index(op.f('ix_content_publications_social_account_id'), table_name='content_publications')
    op.drop_index('ix_content_publications_project_status', table_name='content_publications')
    op.drop_index(op.f('ix_content_publications_project_id'), table_name='content_publications')
    op.drop_index('ix_content_publications_due', table_name='content_publications')
    op.drop_index(op.f('ix_content_publications_draft_id'), table_name='content_publications')
    op.drop_index('ix_content_publications_account', table_name='content_publications')
    op.drop_table('content_publications')
    op.drop_index(op.f('ix_media_assets_workspace_id'), table_name='media_assets')
    op.drop_index('ix_media_assets_workspace_created', table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_uploaded_by'), table_name='media_assets')
    op.drop_index('ix_media_assets_checksum', table_name='media_assets')
    op.drop_index(op.f('ix_media_assets_brand_id'), table_name='media_assets')
    op.drop_index('ix_media_assets_brand', table_name='media_assets')
    op.drop_table('media_assets')

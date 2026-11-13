"""Add automations, automation actions/events/executions/steps, notifications, content tasks.

Phase 10: controlled workflow automations and rule-based execution.

Revision ID: 20261112_0010
Revises: 20261110_0009
Create Date: 2026-11-12 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261112_0010'
down_revision = '20261110_0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('content_projects', sa.Column('assigned_to', sa.Uuid(), nullable=True))
    op.add_column('content_projects', sa.Column('labels', sa.JSON(), nullable=False, server_default='[]'))
    op.create_foreign_key(
        'fk_content_projects_assigned_to_users', 'content_projects', 'users', ['assigned_to'], ['id'], ondelete='SET NULL'
    )
    op.create_index(op.f('ix_content_projects_assigned_to'), 'content_projects', ['assigned_to'], unique=False)

    op.create_table('automations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('brand_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger_type', sa.String(length=64), nullable=False),
    sa.Column('trigger_configuration', sa.JSON(), nullable=False),
    sa.Column('conditions', sa.JSON(), nullable=False),
    sa.Column('max_executions', sa.Integer(), nullable=True),
    sa.Column('cooldown_seconds', sa.Integer(), nullable=False),
    sa.Column('execution_count', sa.Integer(), nullable=False),
    sa.Column('success_count', sa.Integer(), nullable=False),
    sa.Column('failure_count', sa.Integer(), nullable=False),
    sa.Column('last_executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_dry_run', sa.JSON(), nullable=True),
    sa.Column('last_dry_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('draft', 'enabled', 'paused', 'archived')", name='ck_automation_status'),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_automations_brand_id'), 'automations', ['brand_id'], unique=False)
    op.create_index(op.f('ix_automations_created_by'), 'automations', ['created_by'], unique=False)
    op.create_index(op.f('ix_automations_workspace_id'), 'automations', ['workspace_id'], unique=False)
    op.create_index('ix_automations_workspace_status', 'automations', ['workspace_id', 'status'], unique=False)
    op.create_index('ix_automations_workspace_trigger', 'automations', ['workspace_id', 'trigger_type', 'status'], unique=False)

    op.create_table('automation_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('automation_id', sa.Uuid(), nullable=False),
    sa.Column('action_type', sa.String(length=64), nullable=False),
    sa.Column('action_configuration', sa.JSON(), nullable=False),
    sa.Column('execution_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['automation_id'], ['automations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('automation_id', 'execution_order', name='uq_automation_action_order')
    )
    op.create_index(op.f('ix_automation_actions_automation_id'), 'automation_actions', ['automation_id'], unique=False)

    op.create_table('automation_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('source_entity_type', sa.String(length=64), nullable=True),
    sa.Column('source_entity_id', sa.String(length=64), nullable=True),
    sa.Column('event_payload', sa.JSON(), nullable=False),
    sa.Column('dedupe_key', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=120), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('origin_automation_id', sa.Uuid(), nullable=True),
    sa.Column('origin_execution_id', sa.Uuid(), nullable=True),
    sa.Column('chain_depth', sa.Integer(), nullable=False),
    sa.Column('dispatch_summary', sa.JSON(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'processing', 'processed', 'failed')", name='ck_automation_event_status'),
    sa.ForeignKeyConstraint(['origin_automation_id'], ['automations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key', name='uq_automation_event_dedupe')
    )
    op.create_index(op.f('ix_automation_events_workspace_id'), 'automation_events', ['workspace_id'], unique=False)
    op.create_index('ix_automation_events_due', 'automation_events', ['status', 'next_attempt_at'], unique=False)
    op.create_index('ix_automation_events_workspace_occurred', 'automation_events', ['workspace_id', 'occurred_at'], unique=False)
    op.create_index('ix_automation_events_type_occurred', 'automation_events', ['workspace_id', 'event_type', 'occurred_at'], unique=False)

    op.create_table('automation_executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('automation_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('trigger_event_id', sa.Uuid(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger_type', sa.String(length=64), nullable=False),
    sa.Column('execution_context', sa.JSON(), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=120), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('chain_depth', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('retried_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')", name='ck_automation_execution_status'),
    sa.ForeignKeyConstraint(['automation_id'], ['automations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['retried_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['trigger_event_id'], ['automation_events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key', name='uq_automation_execution_idempotency')
    )
    op.create_index(op.f('ix_automation_executions_automation_id'), 'automation_executions', ['automation_id'], unique=False)
    op.create_index(op.f('ix_automation_executions_trigger_event_id'), 'automation_executions', ['trigger_event_id'], unique=False)
    op.create_index(op.f('ix_automation_executions_workspace_id'), 'automation_executions', ['workspace_id'], unique=False)
    op.create_index('ix_automation_executions_automation_created', 'automation_executions', ['automation_id', 'created_at'], unique=False)
    op.create_index('ix_automation_executions_workspace_created', 'automation_executions', ['workspace_id', 'created_at'], unique=False)
    op.create_index('ix_automation_executions_due', 'automation_executions', ['status', 'next_attempt_at'], unique=False)

    op.create_table('automation_execution_steps',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=False),
    sa.Column('action_id', sa.Uuid(), nullable=True),
    sa.Column('action_type', sa.String(length=64), nullable=False),
    sa.Column('execution_order', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('result_summary', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')", name='ck_automation_step_status'),
    sa.ForeignKeyConstraint(['action_id'], ['automation_actions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['execution_id'], ['automation_executions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('execution_id', 'execution_order', name='uq_automation_step_order')
    )
    op.create_index(op.f('ix_automation_execution_steps_execution_id'), 'automation_execution_steps', ['execution_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('automation_id', sa.Uuid(), nullable=True),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=200), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['automation_id'], ['automations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['execution_id'], ['automation_executions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key', name='uq_notification_dedupe')
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    op.create_index(op.f('ix_notifications_workspace_id'), 'notifications', ['workspace_id'], unique=False)
    op.create_index('ix_notifications_user_workspace_created', 'notifications', ['user_id', 'workspace_id', 'created_at'], unique=False)
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'read_at'], unique=False)

    op.create_table('content_tasks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('publication_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('assigned_to', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('automation_id', sa.Uuid(), nullable=True),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=200), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('open', 'done')", name='ck_content_task_status'),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['automation_id'], ['automations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['completed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['execution_id'], ['automation_executions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['project_id'], ['content_projects.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['publication_id'], ['content_publications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key', name='uq_content_task_dedupe')
    )
    op.create_index(op.f('ix_content_tasks_project_id'), 'content_tasks', ['project_id'], unique=False)
    op.create_index(op.f('ix_content_tasks_workspace_id'), 'content_tasks', ['workspace_id'], unique=False)
    op.create_index('ix_content_tasks_workspace_status_created', 'content_tasks', ['workspace_id', 'status', 'created_at'], unique=False)
    op.create_index('ix_content_tasks_assignee_status', 'content_tasks', ['assigned_to', 'status'], unique=False)


def downgrade() -> None:
    op.drop_table('content_tasks')
    op.drop_table('notifications')
    op.drop_table('automation_execution_steps')
    op.drop_table('automation_executions')
    op.drop_table('automation_events')
    op.drop_table('automation_actions')
    op.drop_table('automations')
    op.drop_index(op.f('ix_content_projects_assigned_to'), table_name='content_projects')
    op.drop_constraint('fk_content_projects_assigned_to_users', 'content_projects', type_='foreignkey')
    op.drop_column('content_projects', 'labels')
    op.drop_column('content_projects', 'assigned_to')

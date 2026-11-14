"""Add agent settings, agent workflows, workflow steps, agent executions and agent messages.

Phase 11: multi-agent AI intelligence and orchestration.

Revision ID: 20261113_0011
Revises: 20261112_0010
Create Date: 2026-11-13 00:11:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261113_0011'
down_revision = '20261112_0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agent_settings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('agent_key', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'agent_key', name='uq_agent_setting_workspace_agent')
    )
    op.create_index(op.f('ix_agent_settings_workspace_id'), 'agent_settings', ['workspace_id'], unique=False)

    op.create_table('agent_workflows',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('brand_id', sa.Uuid(), nullable=True),
    sa.Column('workflow_type', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('input_data', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('final_output', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('agent_call_count', sa.Integer(), nullable=False),
    sa.Column('revision_count', sa.Integer(), nullable=False),
    sa.Column('auto_revision_count', sa.Integer(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_by', sa.String(length=120), nullable=True),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_status', sa.String(length=20), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_project_id', sa.Uuid(), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')", name='ck_agent_workflow_status'),
    sa.CheckConstraint("review_status IS NULL OR review_status IN ('pending', 'accepted', 'rejected')", name='ck_agent_workflow_review_status'),
    sa.ForeignKeyConstraint(['accepted_project_id'], ['content_projects.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_workflows_workspace_id'), 'agent_workflows', ['workspace_id'], unique=False)
    op.create_index('ix_agent_workflows_workspace_created', 'agent_workflows', ['workspace_id', 'created_at'], unique=False)
    op.create_index('ix_agent_workflows_due', 'agent_workflows', ['status', 'next_attempt_at'], unique=False)

    op.create_table('agent_workflow_steps',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('step_order', sa.Integer(), nullable=False),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('base_key', sa.String(length=64), nullable=False),
    sa.Column('revision_round', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('agent_key', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=160), nullable=False),
    sa.Column('dependency_configuration', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')", name='ck_agent_step_status'),
    sa.CheckConstraint("kind IN ('context', 'agent', 'compile')", name='ck_agent_step_kind'),
    sa.ForeignKeyConstraint(['workflow_id'], ['agent_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'step_key', name='uq_agent_step_key'),
    sa.UniqueConstraint('workflow_id', 'step_order', name='uq_agent_step_order')
    )
    op.create_index(op.f('ix_agent_workflow_steps_workflow_id'), 'agent_workflow_steps', ['workflow_id'], unique=False)

    op.create_table('agent_executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('step_id', sa.Uuid(), nullable=True),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('agent_key', sa.String(length=64), nullable=False),
    sa.Column('agent_version', sa.String(length=20), nullable=True),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('input_data', sa.JSON(), nullable=False),
    sa.Column('output_data', sa.JSON(), nullable=True),
    sa.Column('model_name', sa.String(length=120), nullable=True),
    sa.Column('token_usage', sa.JSON(), nullable=True),
    sa.Column('execution_duration_ms', sa.Integer(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('running', 'succeeded', 'failed', 'cancelled')", name='ck_agent_execution_status'),
    sa.ForeignKeyConstraint(['step_id'], ['agent_workflow_steps.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_id'], ['agent_workflows.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_executions_workflow_id'), 'agent_executions', ['workflow_id'], unique=False)
    op.create_index(op.f('ix_agent_executions_workspace_id'), 'agent_executions', ['workspace_id'], unique=False)
    op.create_index(op.f('ix_agent_executions_step_id'), 'agent_executions', ['step_id'], unique=False)
    op.create_index('ix_agent_executions_workflow_started', 'agent_executions', ['workflow_id', 'started_at'], unique=False)

    op.create_table('agent_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('sender_agent', sa.String(length=64), nullable=False),
    sa.Column('receiver_agent', sa.String(length=64), nullable=False),
    sa.Column('message_type', sa.String(length=32), nullable=False),
    sa.Column('structured_payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['agent_workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_messages_workflow_id'), 'agent_messages', ['workflow_id'], unique=False)
    op.create_index('ix_agent_messages_workflow_created', 'agent_messages', ['workflow_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('agent_messages')
    op.drop_table('agent_executions')
    op.drop_table('agent_workflow_steps')
    op.drop_table('agent_workflows')
    op.drop_table('agent_settings')

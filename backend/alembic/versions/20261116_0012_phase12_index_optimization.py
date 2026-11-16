"""Index optimization based on measured query patterns.

Phase 12: production optimization. Indexes only - no table, column or data
change, so both directions are safe on a populated database.

Added (each serves a specific query, see docs/performance-report.md):

* content_projects (workspace_id, created_at) - the paginated project list.
* content_approvals (created_at) WHERE status = 'pending' - the approval
  reminder scan that runs in the worker.
* Partial indexes on nullable foreign keys that PostgreSQL must scan when the
  parent row is deleted (automation edits and deletes, draft deletion).

Removed: five indexes that exactly duplicate a unique constraint or another
index on the same columns (they cost writes and storage, and are never chosen
over their twin).

On PostgreSQL every statement runs with CREATE/DROP INDEX CONCURRENTLY outside
a transaction, so writes to the tables are not blocked while an index builds.
If a concurrent build is interrupted it leaves an INVALID index: drop it
(``DROP INDEX CONCURRENTLY <name>``) and run the migration again - every
statement is idempotent (IF [NOT] EXISTS).

Revision ID: 20261116_0012
Revises: 20261113_0011
Create Date: 2026-11-16 00:12:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261116_0012'
down_revision = '20261113_0011'
branch_labels = None
depends_on = None

# (index name, table, columns, partial predicate or None)
NEW_INDEXES = [
    ('ix_content_projects_workspace_created', 'content_projects', ['workspace_id', 'created_at'], None),
    ('ix_content_approvals_pending_created', 'content_approvals', ['created_at'], "status = 'pending'"),
    ('ix_notifications_execution', 'notifications', ['execution_id'], 'execution_id IS NOT NULL'),
    ('ix_notifications_automation', 'notifications', ['automation_id'], 'automation_id IS NOT NULL'),
    ('ix_content_tasks_execution', 'content_tasks', ['execution_id'], 'execution_id IS NOT NULL'),
    ('ix_content_tasks_automation', 'content_tasks', ['automation_id'], 'automation_id IS NOT NULL'),
    ('ix_content_tasks_publication', 'content_tasks', ['publication_id'], 'publication_id IS NOT NULL'),
    ('ix_automation_execution_steps_action', 'automation_execution_steps', ['action_id'], 'action_id IS NOT NULL'),
    (
        'ix_automation_events_origin_automation',
        'automation_events',
        ['origin_automation_id'],
        'origin_automation_id IS NOT NULL',
    ),
    ('ix_post_analytics_draft', 'post_analytics', ['draft_id'], 'draft_id IS NOT NULL'),
    ('ix_agent_workflows_accepted_project', 'agent_workflows', ['accepted_project_id'], 'accepted_project_id IS NOT NULL'),
]

# (index name, table, columns) - each one duplicates the index named in the comment.
DUPLICATE_INDEXES = [
    ('ix_media_assets_brand', 'media_assets', ['brand_id']),  # = ix_media_assets_brand_id
    ('ix_content_publications_account', 'content_publications', ['social_account_id']),  # = ..._social_account_id
    ('ix_content_drafts_platform', 'content_drafts', ['project_id', 'platform']),  # = uq_content_draft_project_platform
    ('ix_content_versions_draft_number', 'content_versions', ['draft_id', 'version_number']),  # = uq_content_version_draft_number
    ('ix_research_reports_research_id', 'research_reports', ['research_id']),  # = unique(research_id)
]


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


def _create(name: str, table: str, columns: list[str], where: str | None) -> None:
    predicate = sa.text(where) if where else None
    if _is_postgresql():
        op.create_index(
            name, table, columns, unique=False, if_not_exists=True,
            postgresql_concurrently=True, postgresql_where=predicate,
        )
    else:
        op.create_index(name, table, columns, unique=False, if_not_exists=True, sqlite_where=predicate)


def _drop(name: str, table: str) -> None:
    if _is_postgresql():
        op.drop_index(name, table_name=table, if_exists=True, postgresql_concurrently=True)
    else:
        op.drop_index(name, table_name=table, if_exists=True)


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        for name, table, columns, where in NEW_INDEXES:
            _create(name, table, columns, where)
        for name, table, _columns in DUPLICATE_INDEXES:
            _drop(name, table)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns in DUPLICATE_INDEXES:
            _create(name, table, columns, None)
        for name, table, _columns, _where in NEW_INDEXES:
            _drop(name, table)

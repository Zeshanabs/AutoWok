"""Allow Groq as an AI provider.

Revision ID: 20261103_0003
Revises: 20261102_0002
Create Date: 2026-11-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261103_0003"
down_revision: Union[str, None] = "20261102_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_provider_configs") as batch_op:
        batch_op.drop_constraint("ck_ai_provider_name", type_="check")
        batch_op.create_check_constraint(
            "ck_ai_provider_name",
            "provider_name IN ('openai', 'anthropic', 'gemini', 'groq', 'openai_compatible')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_provider_configs") as batch_op:
        batch_op.drop_constraint("ck_ai_provider_name", type_="check")
        batch_op.create_check_constraint(
            "ck_ai_provider_name",
            "provider_name IN ('openai', 'anthropic', 'gemini', 'openai_compatible')",
        )

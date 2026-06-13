"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-13

"""

import sqlalchemy as sa

from alembic import op

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user',
        sa.Column('id', sa.BIGINT(), nullable=False),
        sa.Column('telegram_id', sa.BIGINT(), nullable=False),
        sa.Column(
            'joined_date',
            sa.TIMESTAMP(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_user_telegram_id'), 'user', ['telegram_id'], unique=True
    )

    op.create_table(
        'download_queue',
        sa.Column('id', sa.BIGINT(), nullable=False),
        sa.Column('chat_id', sa.BIGINT(), nullable=False),
        sa.Column('bot_message_id', sa.BIGINT(), nullable=False),
        sa.Column('user_message_id', sa.BIGINT(), nullable=False),
        sa.Column('query', sa.String(), nullable=False),
        sa.Column(
            'queued_date',
            sa.TIMESTAMP(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('download_queue')
    op.drop_index(op.f('ix_user_telegram_id'), table_name='user')
    op.drop_table('user')

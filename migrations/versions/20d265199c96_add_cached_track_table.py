"""add cached_track table

Revision ID: 20d265199c96
Revises: 0001
Create Date: 2026-06-14 02:39:11.896203

"""

import sqlalchemy as sa

from alembic import op

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '20d265199c96'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'cached_track',
        sa.Column('id', sa.BIGINT(), nullable=False),
        sa.Column('query_key', sa.String(), nullable=False),
        sa.Column('file_id', sa.String(), nullable=False),
        sa.Column(
            'cached_date',
            sa.TIMESTAMP(),
            server_default=sa.text('NOW()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_cached_track_query_key'),
        'cached_track',
        ['query_key'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_cached_track_query_key'), table_name='cached_track')
    op.drop_table('cached_track')

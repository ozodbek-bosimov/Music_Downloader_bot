"""add callback_query_id to download_queue

Revision ID: 30e376200d97
Revises: 20d265199c96
Create Date: 2026-07-13 03:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from collections.abc import Sequence

revision: str = '30e376200d97'
down_revision: str | None = '20d265199c96'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'download_queue',
        sa.Column('callback_query_id', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('download_queue', 'callback_query_id')

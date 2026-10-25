"""Append-only cloud finance event journal."""
from alembic import op
import sqlalchemy as sa
revision = '0024_finance_events'
down_revision = '0023_money_fund_fields'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('finance_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_key', sa.String(255), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('effects', sa.JSON(), nullable=False),
        sa.UniqueConstraint('user_id', 'request_key', name='uq_finance_request'))
    for name in ('user_id', 'kind', 'effective_at'):
        op.create_index('ix_finance_events_'+name, 'finance_events', [name])

def downgrade():
    op.drop_table('finance_events')

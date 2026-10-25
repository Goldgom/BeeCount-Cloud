"""Read-only cloud data sources.

Revision ID: 0026
Revises: 0025
"""
from alembic import op
import sqlalchemy as sa
revision = '0026_data_sources'
down_revision = '0025_investment_valuation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('data_sources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False), sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('credentials_encrypted', sa.Text(), nullable=False), sa.Column('account_id', sa.String(255)),
        sa.Column('coverage_policy', sa.String(32), nullable=False), sa.Column('poll_interval_seconds', sa.Integer(), nullable=False),
        sa.Column('paused', sa.Boolean(), nullable=False), sa.Column('symbols', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('cursors', sa.JSON(), nullable=False), sa.Column('error', sa.String(120)),
        *[sa.Column(n, sa.DateTime(timezone=True)) for n in ('last_attempt_at','last_success_at','next_sync_at','lock_until')],
        sa.Column('lock_token', sa.String(36)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_data_sources_user_id', 'data_sources', ['user_id'])
    op.create_table('data_source_events', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('data_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(80), nullable=False), sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('source_id','kind','external_id',name='uq_data_source_event'))
    op.create_index('ix_data_source_events_source_id','data_source_events',['source_id'])
    op.create_table('data_source_sync_receipts', sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(36), sa.ForeignKey('data_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_key', sa.String(128), nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('source_id','request_key',name='uq_data_source_sync_key'))
    op.create_index('ix_data_source_sync_receipts_source_id','data_source_sync_receipts',['source_id'])


def downgrade():
    for table in ('data_source_sync_receipts','data_source_events','data_sources'):
        op.drop_table(table)

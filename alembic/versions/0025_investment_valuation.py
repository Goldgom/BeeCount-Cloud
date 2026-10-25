"""Explicit investment valuation modes and unknown costs.

Existing zero costs are preserved, not guessed to mean unknown. New omitted
costs are NULL. No ledger or event history is rewritten.
"""
import sqlalchemy as sa
from alembic import op
revision = '0025_investment_valuation'
down_revision = '0024_finance_events'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('investment_products') as batch:
        batch.alter_column('cost_basis', existing_type=sa.Float(), nullable=True)
        batch.add_column(sa.Column('valuation_mode', sa.String(32), nullable=False, server_default='shares_nav'))
        batch.add_column(sa.Column('snapshot_amount', sa.Float(), nullable=True))
        batch.add_column(sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('valuation_source', sa.String(255), nullable=True))


def downgrade():
    # Unknown costs cannot be truthfully converted to a required numeric value.
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM investment_products WHERE cost_basis IS NULL')).scalar():
        raise RuntimeError('Cannot downgrade unknown costs; explicitly resolve them first')
    with op.batch_alter_table('investment_products') as batch:
        for name in ('valuation_source', 'snapshot_at', 'snapshot_amount', 'valuation_mode'):
            batch.drop_column(name)
        batch.alter_column('cost_basis', existing_type=sa.Float(), nullable=False)

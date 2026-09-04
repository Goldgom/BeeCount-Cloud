"""Add money-market fund accounting fields."""
import sqlalchemy as sa
from alembic import op

revision = "0023_money_fund_fields"
down_revision = "0022_investment_product_account_link"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("investment_products", sa.Column("is_money_fund", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("investment_products", sa.Column("net_subscription_principal", sa.Float(), nullable=True))
    op.add_column("investment_products", sa.Column("daily_income", sa.Float(), nullable=True))

def downgrade() -> None:
    op.drop_column("investment_products", "daily_income")
    op.drop_column("investment_products", "net_subscription_principal")
    op.drop_column("investment_products", "is_money_fund")

"""Add investment metadata to account projection."""
import sqlalchemy as sa
from alembic import op

revision = "0021_investment_account_metadata"
down_revision = "0020_investment_products"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("user_account_projection", sa.Column("investment_product_name", sa.Text(), nullable=True))
    op.add_column("user_account_projection", sa.Column("investment_product_symbol", sa.String(64), nullable=True))
    op.add_column("user_account_projection", sa.Column("investment_product_market", sa.String(32), nullable=True))

def downgrade() -> None:
    op.drop_column("user_account_projection", "investment_product_market")
    op.drop_column("user_account_projection", "investment_product_symbol")
    op.drop_column("user_account_projection", "investment_product_name")

"""Bind investment holdings to stable investment account ids.

``account_name`` remains as a compatibility/display field.  Existing rows are
backfilled only where a same-named investment account exists for the owner.
"""
import sqlalchemy as sa
from alembic import op


revision = "0022_investment_product_account_link"
down_revision = "0021_investment_account_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("investment_products", sa.Column("account_id", sa.String(255), nullable=True))
    op.create_index("ix_investment_products_user_account", "investment_products", ["user_id", "account_id"])
    # A scalar subquery is supported by SQLite and PostgreSQL.  It deliberately
    # only considers investment accounts, so a wallet with the same label is
    # never accidentally linked as an investment account.
    op.execute("""
        UPDATE investment_products
        SET account_id = (
            SELECT a.sync_id
            FROM user_account_projection AS a
            WHERE a.user_id = investment_products.user_id
              AND a.account_type = 'investment'
              AND a.name = investment_products.account_name
            LIMIT 1
        )
        WHERE account_name IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_investment_products_user_account", table_name="investment_products")
    op.drop_column("investment_products", "account_id")

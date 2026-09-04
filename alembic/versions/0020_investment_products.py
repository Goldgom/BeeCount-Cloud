"""Investment holdings managed by MCP/web."""
import sqlalchemy as sa
from alembic import op

revision = "0020_investment_products"
down_revision = "0019_account_hidden"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investment_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("market", sa.String(32)),
        sa.Column("currency", sa.String(16), nullable=False, server_default="CNY"),
        sa.Column("account_name", sa.String(255)),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_basis", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_price", sa.Float()),
        sa.Column("price_source", sa.String(64)),
        sa.Column("price_updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_market_close", sa.Float()),
        sa.Column("day_change", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_investment_products_user_id", "investment_products", ["user_id"])
    op.create_index("ix_investment_products_symbol", "investment_products", ["symbol"])


def downgrade() -> None:
    op.drop_table("investment_products")

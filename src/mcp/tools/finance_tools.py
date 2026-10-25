"""Register cloud finance tools without changing mobile sync semantics."""
import asyncio
from mcp.server.fastmcp import Context
from ...database import SessionLocal
from ...security import SCOPE_MCP_READ, SCOPE_MCP_WRITE
from ...services import finance

_ws_manager = None

def set_ws_manager(manager):
    global _ws_manager
    _ws_manager = manager


def register(mcp, logged_call):
    @mcp.tool()
    async def finance_operation(ctx: Context, kind: str, idempotency_key: str, data: dict) -> dict:
        """Append finance event. Kinds: reconciliation, reversal, transfer, receivable,
        receivable_installment, repayment, snapshot, investment_event.
        Reconciliation requires account_id,target_balance,expected_balance,effective_at,
        source,reason. Transfer requires both account IDs, amounts,currencies,source,
        external_id; optional fee_amount/fee_account_id/fee_currency. Never modifies
        initial_balance or fabricates income. See docs/FINANCE_API.md for full contract.
        """
        def run(user_id):
            with SessionLocal() as db:
                try:
                    result = finance.execute(db, user_id=user_id, kind=kind, key=idempotency_key, data=data)
                    db.commit()
                    return result
                except Exception:
                    db.rollback()
                    raise
        async def body(user):
            result = await asyncio.to_thread(run, user.id)
            if _ws_manager is not None:
                await _ws_manager.broadcast_to_user(user.id, {'type':'sync_change', 'scope':'user',
                    'entity_type':'finance_event', 'finance_event_id':result['id']})
            return result
        return await logged_call(ctx, name='finance_operation', scope=SCOPE_MCP_WRITE,
                                 kwargs={'kind': kind}, body=body)

    @mcp.tool()
    async def finance_read(ctx: Context, view: str = 'balances', start: str | None = None,
                           end: str | None = None) -> dict:
        """Read balances, events, receivables, or period_report. Report requires start/end
        timezone-aware timestamps. Missing historical data/returns stay null.
        """
        def run(user_id):
            with SessionLocal() as db:
                if view == 'balances':
                    result = finance.account_balances(db, user_id=user_id)
                elif view == 'events':
                    result = [finance.output(e) for e in finance.events(db, user_id)]
                elif view == 'receivables':
                    result = finance.receivables(db, user_id)
                elif view == 'period_report' and start and end:
                    result = finance.period_report(db, user_id, start, end)
                else:
                    finance.fail('Unsupported view or missing start/end')
                return {'data': result}
        return await logged_call(ctx, name='finance_read', scope=SCOPE_MCP_READ,
                                 kwargs={'view': view}, body=lambda user: asyncio.to_thread(run, user.id))

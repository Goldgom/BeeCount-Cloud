"""Cloud finance journal API (not mobile sync)."""
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db
from ..deps import get_current_user, require_any_scopes
from ..models import User
from .read._shared import _READ_SCOPE_DEP
from .write._shared import _WRITE_SCOPE_DEP
from ..services import finance

router = APIRouter(prefix='/finance', tags=['finance'])
read_scope = _READ_SCOPE_DEP
write_scope = _WRITE_SCOPE_DEP

class Operation(BaseModel):
    kind: str
    data: dict = Field(default_factory=dict)

@router.post('/events')
async def post_event(body: Operation, request: Request, idempotency_key: str = Header(alias='Idempotency-Key'),
               user: User = Depends(get_current_user), db: Session = Depends(get_db),
               _scope=Depends(write_scope)):
    try:
        result = finance.execute(db, user_id=user.id, kind=body.kind, key=idempotency_key, data=body.data)
        db.commit()
        manager = getattr(request.app.state, 'ws_manager', None)
        if manager:
            await manager.broadcast_to_user(user.id, {'type': 'sync_change', 'scope': 'user',
                'entity_type': 'finance_event', 'finance_event_id': result['id']})
        return result
    except Exception:
        db.rollback()
        raise

@router.get('/balances')
def balances(user: User = Depends(get_current_user), db: Session = Depends(get_db), _scope=Depends(read_scope)):
    return finance.account_balances(db, user_id=user.id)

@router.get('/events')
def list_events(user: User = Depends(get_current_user), db: Session = Depends(get_db), _scope=Depends(read_scope)):
    return [finance.output(e) for e in finance.events(db, user.id)]

@router.get('/receivables')
def receivables(user: User = Depends(get_current_user), db: Session = Depends(get_db), _scope=Depends(read_scope)):
    return finance.receivables(db, user.id)

@router.get('/period-report')
def period_report(start: str, end: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db), _scope=Depends(read_scope)):
    return finance.period_report(db, user.id, start, end)

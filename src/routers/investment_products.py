"""Authenticated REST CRUD for cloud investment holdings.

This API is deliberately separate from MCP: mobile clients use their normal
JWT and never need to store or receive a Personal Access Token.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_any_scopes
from ..models import InvestmentProduct, User, UserAccountProjection
from ..services.investment_accounts import get_investment_account
from ..security import SCOPE_APP_WRITE, SCOPE_WEB_WRITE

router = APIRouter()
_WRITE_SCOPE = require_any_scopes(SCOPE_APP_WRITE, SCOPE_WEB_WRITE)


class InvestmentProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    symbol: str = Field(min_length=1, max_length=64)
    quantity: float = Field(ge=0)
    cost_basis: float | None = Field(default=None, ge=0, description="Optional per-unit cost")
    currency: str = Field(default="CNY", min_length=1, max_length=16)
    market: str | None = Field(default=None, max_length=32)
    account_id: str | None = Field(default=None, min_length=1, max_length=255,
                                  description="Investment account id (preferred stable binding)")
    # Compatibility input for older clients.  It is resolved to account_id and
    # never stored as an independent relationship.
    account_name: str | None = Field(default=None, max_length=255)
    current_price: float | None = Field(default=None, ge=0, description="Manual price; omit for auto quote")
    last_market_close: float | None = Field(default=None, ge=0)
    day_change: float | None = None

    @field_validator("name", "symbol", "currency")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class InvestmentProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    symbol: str | None = Field(default=None, min_length=1, max_length=64)
    quantity: float | None = Field(default=None, ge=0)
    cost_basis: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=1, max_length=16)
    market: str | None = Field(default=None, max_length=32)
    account_id: str | None = Field(default=None, min_length=1, max_length=255)
    account_name: str | None = Field(default=None, max_length=255)
    current_price: float | None = Field(default=None, ge=0)
    last_market_close: float | None = Field(default=None, ge=0)
    day_change: float | None = None
    use_auto_price: bool = False


class InvestmentProductOut(BaseModel):
    id: str
    name: str
    symbol: str
    market: str | None
    currency: str
    account_id: str | None
    account_name: str | None
    quantity: float
    cost_basis: float
    current_price: float | None
    price_mode: str


def _out(row: InvestmentProduct) -> InvestmentProductOut:
    return InvestmentProductOut(
        id=row.id, name=row.name, symbol=row.symbol, market=row.market,
        currency=row.currency, account_id=row.account_id, account_name=row.account_name,
        quantity=float(row.quantity or 0), cost_basis=float(row.cost_basis or 0),
        current_price=row.current_price,
        price_mode="manual" if row.price_source == "manual" else "auto",
    )


@router.post("", response_model=InvestmentProductOut, status_code=status.HTTP_201_CREATED)
def create_investment_product(
    req: InvestmentProductCreate,
    _scopes: set[str] = Depends(_WRITE_SCOPE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvestmentProductOut:
    account_id = req.account_id or _account_id_by_legacy_name(db, current_user.id, req.account_name)
    account = _require_investment_account(db, current_user.id, account_id)
    row = InvestmentProduct(
        id=str(uuid4()), user_id=current_user.id, name=req.name.strip(),
        symbol=req.symbol.strip().upper(), quantity=req.quantity,
        cost_basis=req.cost_basis or 0, currency=req.currency.strip().upper(),
        market=req.market.strip() if req.market else None,
        account_id=account.sync_id, account_name=account.name,
        current_price=req.current_price, last_market_close=req.last_market_close,
        day_change=req.day_change, price_source="manual" if req.current_price is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.patch("/{product_id}", response_model=InvestmentProductOut)
def update_investment_product(
    product_id: str,
    req: InvestmentProductPatch,
    _scopes: set[str] = Depends(_WRITE_SCOPE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvestmentProductOut:
    row = db.scalar(select(InvestmentProduct).where(InvestmentProduct.id == product_id, InvestmentProduct.user_id == current_user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Investment product not found")
    payload = req.model_dump(exclude_unset=True)
    if "account_id" in payload:
        account = _require_investment_account(db, current_user.id, payload.pop("account_id"))
        row.account_id, row.account_name = account.sync_id, account.name
    elif "account_name" in payload:
        account = _require_investment_account(
            db, current_user.id, _account_id_by_legacy_name(db, current_user.id, payload["account_name"])
        )
        row.account_id, row.account_name = account.sync_id, account.name
        payload.pop("account_name")
    if payload.pop("use_auto_price", False):
        row.current_price = row.last_market_close = row.day_change = None
        row.price_source = None
    for key, value in payload.items():
        if key == "current_price":
            # Explicit JSON null is the REST representation of a blank field:
            # clear the override and resume the provider on the next refresh.
            if value is None:
                row.price_source = None
                row.last_market_close = None
                row.day_change = None
            else:
                row.price_source = "manual"
        if key == "cost_basis" and value is None:
            value = 0
        if key in {"symbol", "currency"} and value is not None:
            value = value.strip().upper()
        elif key in {"name", "market", "account_name"} and isinstance(value, str):
            value = value.strip() or None
        if key == "name" and value is None:
            raise HTTPException(status_code=422, detail="name must not be blank")
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _out(row)


def _account_id_by_legacy_name(db: Session, user_id: str, account_name: str | None) -> str | None:
    if not account_name or not account_name.strip():
        return None
    return db.scalar(select(UserAccountProjection.sync_id).where(
        UserAccountProjection.user_id == user_id,
        UserAccountProjection.account_type == "investment",
        UserAccountProjection.name == account_name.strip(),
    ))


def _require_investment_account(db: Session, user_id: str, account_id: str | None) -> UserAccountProjection:
    if not account_id:
        raise HTTPException(status_code=422, detail="account_id is required and must reference an investment account")
    account = get_investment_account(db, user_id=user_id, account_id=account_id.strip())
    if account is None:
        raise HTTPException(status_code=422, detail="account_id must reference one of your investment accounts")
    return account


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investment_product(
    product_id: str,
    _scopes: set[str] = Depends(_WRITE_SCOPE),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    row = db.scalar(select(InvestmentProduct).where(InvestmentProduct.id == product_id, InvestmentProduct.user_id == current_user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Investment product not found")
    db.delete(row)
    db.commit()

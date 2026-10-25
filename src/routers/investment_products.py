"""Authenticated REST CRUD for cloud investment holdings.

This API is deliberately separate from MCP: mobile clients use their normal
JWT and never need to store or receive a Personal Access Token.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=255)
    symbol: str = Field(min_length=1, max_length=64)
    quantity: float = Field(default=0, ge=0)
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
    is_money_fund: bool = False
    net_subscription_principal: float | None = Field(default=None, ge=0)
    daily_income: float | None = None
    valuation_mode: Literal["shares_nav", "amount_snapshot", "money_fund"] = "shares_nav"
    snapshot_amount: float | None = Field(default=None, ge=0)
    snapshot_at: datetime | None = None
    valuation_source: str | None = None

    @field_validator("name", "symbol", "currency")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


    @field_validator("snapshot_at")
    @classmethod
    def timestamp_has_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("snapshot_at must include timezone")
        return value


class InvestmentProductPatch(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
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
    is_money_fund: bool | None = None
    net_subscription_principal: float | None = Field(default=None, ge=0)
    daily_income: float | None = None
    valuation_mode: Literal["shares_nav", "amount_snapshot", "money_fund"] | None = None
    snapshot_amount: float | None = Field(default=None, ge=0)
    snapshot_at: datetime | None = None
    valuation_source: str | None = None
    clear_cost_basis: bool = False


    @field_validator("snapshot_at")
    @classmethod
    def timestamp_has_timezone(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("snapshot_at must include timezone")
        return value


class InvestmentProductOut(BaseModel):
    id: str
    name: str
    symbol: str
    market: str | None
    currency: str
    account_id: str | None
    account_name: str | None
    quantity: float
    cost_basis: float | None
    valuation_mode: str
    snapshot_amount: float | None
    snapshot_at: datetime | None
    valuation_source: str | None
    current_price: float | None
    price_mode: str
    is_money_fund: bool
    net_subscription_principal: float | None
    daily_income: float | None


def _out(row: InvestmentProduct) -> InvestmentProductOut:
    return InvestmentProductOut(
        id=row.id, name=row.name, symbol=row.symbol, market=row.market,
        currency=row.currency, account_id=row.account_id, account_name=row.account_name,
        quantity=float(row.quantity or 0), cost_basis=row.cost_basis,
        valuation_mode="money_fund" if row.is_money_fund else row.valuation_mode,
        snapshot_amount=row.snapshot_amount, snapshot_at=row.snapshot_at, valuation_source=row.valuation_source,
        current_price=1.0 if row.is_money_fund else row.current_price,
        price_mode="manual" if row.price_source == "manual" else "auto",
        is_money_fund=bool(row.is_money_fund), net_subscription_principal=row.net_subscription_principal,
        daily_income=row.daily_income,
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
    money_fund = req.is_money_fund or req.valuation_mode == "money_fund"
    principal = req.net_subscription_principal
    if money_fund:
        principal = req.quantity * req.cost_basis if principal is None and req.cost_basis is not None else principal
        effective_cost = principal / req.quantity if req.quantity > 0 and principal is not None else (0.0 if req.quantity == 0 else None)
    else:
        effective_cost = req.cost_basis
    row = InvestmentProduct(
        id=str(uuid4()), user_id=current_user.id, name=req.name.strip(),
        symbol=req.symbol.strip().upper(), quantity=req.quantity,
        cost_basis=effective_cost, currency=req.currency.strip().upper(), is_money_fund=money_fund,
        valuation_mode="money_fund" if money_fund else req.valuation_mode,
        snapshot_amount=req.snapshot_amount, snapshot_at=req.snapshot_at, valuation_source=req.valuation_source,
        net_subscription_principal=principal if money_fund else None, daily_income=req.daily_income,
        market=req.market.strip() if req.market else None,
        account_id=account.sync_id, account_name=account.name,
        current_price=1.0 if money_fund else req.current_price, last_market_close=req.last_market_close,
        day_change=req.day_change, price_source="money_fund" if money_fund else ("manual" if req.current_price is not None else None),
    )
    if row.current_price is not None:
        row.price_updated_at = datetime.now(timezone.utc)
    _validate_valuation(row)
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
    if payload.pop("clear_cost_basis", False):
        row.cost_basis = None
    if payload.get("valuation_mode") is not None:
        payload["is_money_fund"] = payload["valuation_mode"] == "money_fund"
    if payload.get("is_money_fund") is False and row.valuation_mode == "money_fund" and "valuation_mode" not in payload:
        payload["valuation_mode"] = "shares_nav"
    for required in ("name", "symbol", "currency", "quantity", "valuation_mode", "is_money_fund"):
        if required in payload and payload[required] is None:
            raise HTTPException(status_code=422, detail=required + " cannot be null")
    money_fund_changed = payload.get("is_money_fund", row.is_money_fund)
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
        if key in {"symbol", "currency"} and value is not None:
            value = value.strip().upper()
        elif key in {"name", "market", "account_name"} and isinstance(value, str):
            value = value.strip() or None
        if key == "name" and value is None:
            raise HTTPException(status_code=422, detail="name must not be blank")
        setattr(row, key, value)
    if money_fund_changed:
        row.current_price = 1.0
        row.valuation_mode = "money_fund"
        row.cost_basis = (row.net_subscription_principal / row.quantity if row.net_subscription_principal is not None else None) if row.quantity else 0.0
        row.price_source = "money_fund"
    elif payload.get("is_money_fund") is False and "current_price" not in payload:
        row.current_price = row.last_market_close = row.day_change = None
        row.price_source = None
    if "current_price" in payload:
        row.price_updated_at = datetime.now(timezone.utc) if row.current_price is not None else None
    _validate_valuation(row)
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


def _validate_valuation(row):
    if row.valuation_mode == "amount_snapshot" and (row.snapshot_amount is None or row.snapshot_at is None or not row.valuation_source):
        raise HTTPException(status_code=422, detail="amount_snapshot requires snapshot_amount, snapshot_at and valuation_source")

"""Best-effort quote lookup for investment products.

Yahoo Finance's public chart endpoint is used by default.  Deployments can
provide ``INVESTMENT_PRICE_URL`` with ``{symbol}`` and ``{market}`` tokens to
use an internal/provider endpoint returning ``{"price": 123.4}``.
"""
from __future__ import annotations

import httpx
from ..config import get_settings


async def fetch_price(symbol: str, market: str | None = None) -> tuple[float, str]:
    settings = get_settings()
    custom = getattr(settings, "investment_price_url", None)
    if custom:
        url = custom.format(symbol=symbol, market=market or "")
        async with httpx.AsyncClient(timeout=8) as client:
            data = (await client.get(url)).json()
        return float(data["price"]), "custom"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "BeeCount-Cloud"}) as client:
        data = (await client.get(url)).json()
    result = data["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    if price is None:
        raise RuntimeError("price unavailable")
    return float(price), "yahoo"

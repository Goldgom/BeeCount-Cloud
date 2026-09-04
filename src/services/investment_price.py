"""Free/open quote providers for investment products.

Provider selection lives here so routers and MCP share the same behaviour.
Yahoo Finance's public chart endpoint is the default; deployments may provide
``INVESTMENT_PRICE_URL``. A manual current price is never overwritten.
"""
from __future__ import annotations

import httpx
from ..config import get_settings


async def fetch_price(symbol: str, market: str | None = None) -> dict[str, float | str | None]:
    settings = get_settings()
    provider = (getattr(settings, "investment_price_provider", "yahoo") or "yahoo").lower()
    custom = getattr(settings, "investment_price_url", None)
    if custom:
        url = custom.format(symbol=symbol, market=market or "")
        async with httpx.AsyncClient(timeout=8) as client:
            data = (await client.get(url)).json()
        return {"price": float(data["price"]), "source": provider, "previous_close": data.get("previous_close"), "day_change": data.get("day_change")}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "BeeCount-Cloud"}) as client:
        data = (await client.get(url)).json()
    result = data["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    if price is None:
        raise RuntimeError("price unavailable")
    previous_close = meta.get("previousClose")
    return {
        "price": float(price),
        "source": "yahoo",
        "previous_close": float(previous_close) if previous_close is not None else None,
        "day_change": float(price) - float(previous_close) if previous_close is not None else None,
    }

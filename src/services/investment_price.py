"""Free/open quote providers for investment products.

Provider selection lives here so routers and MCP share the same behaviour.
Yahoo Finance's public chart endpoint is the default; deployments may provide
``INVESTMENT_PRICE_URL``. A manual current price is never overwritten.
"""
from __future__ import annotations

import httpx
import re
from urllib.parse import quote
from ..config import get_settings


async def fetch_price(symbol: str, market: str | None = None) -> dict[str, float | str | None]:
    settings = get_settings()
    provider = (getattr(settings, "investment_price_provider", "yahoo") or "yahoo").lower()
    custom = getattr(settings, "investment_price_url", None)
    if custom:
        url = custom.format(symbol=symbol, market=market or "")
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        return {"price": float(data["price"]), "source": provider, "previous_close": data.get("previous_close"), "day_change": data.get("day_change")}
    clean_symbol = str(symbol or "").strip().upper()
    market_key = str(market or "").strip().lower()
    digits = re.sub(r"\D", "", clean_symbol)

    # China funds are not listed in Yahoo's chart API.  Eastmoney's public
    # fund-gz endpoint supplies the estimated NAV and previous NAV without a
    # key; explicit fund markets and the common six-digit fund-code range
    # beginning with ``1`` use this provider.
    if market_key in {"fund", "funds", "基金", "公募基金", "cn-fund", "cn_fund"} or (not market_key and re.fullmatch(r"1\d{5}", digits)):
        return await _fetch_cn_fund(digits or clean_symbol)

    yahoo_symbol = _normalize_yahoo_symbol(clean_symbol, market_key)
    try:
        return await _fetch_yahoo(yahoo_symbol)
    except Exception as yahoo_error:
        # Yahoo is frequently unreachable from mainland deployments. Tencent's
        # public quote endpoint is a no-key fallback for A shares/ETFs.
        if digits and len(digits) == 6 and _is_cn_stock_market(market_key, digits):
            try:
                return await _fetch_tencent(digits, market_key)
            except Exception:
                pass
        raise RuntimeError(f"quote unavailable for {clean_symbol}: {yahoo_error}") from yahoo_error


def _is_cn_stock_market(market: str, digits: str) -> bool:
    return market in {"cn", "a", "stock", "stocks", "sh", "sz", "sse", "szse", "沪", "深", "沪市", "深市"} or digits.startswith(("0", "3", "6"))


def _normalize_yahoo_symbol(symbol: str, market: str) -> str:
    if re.fullmatch(r"\d{6}", symbol):
        suffix = ".SS" if market in {"sh", "sse", "沪", "沪市"} or (not market and symbol.startswith("6")) else ".SZ"
        return symbol + suffix
    return symbol


async def _fetch_yahoo(symbol: str) -> dict[str, float | str | None]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='.') }"
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "BeeCount-Cloud"}) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError("Yahoo returned no result")
    meta = result[0].get("meta") or {}
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    if price is None:
        raise RuntimeError("price unavailable")
    previous_close = meta.get("previousClose")
    return {"price": float(price), "source": "yahoo",
            "previous_close": float(previous_close) if previous_close is not None else None,
            "day_change": float(price) - float(previous_close) if previous_close is not None else None}


async def _fetch_tencent(symbol: str, market: str) -> dict[str, float | str | None]:
    """Fetch a mainland A-share/ETF quote from Tencent's public endpoint.

    Tencent is used because Sina frequently returns 403 to server-side clients.
    """
    prefix = "sh" if market in {"sh", "sse", "沪", "沪市"} or symbol.startswith("6") else "sz"
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "BeeCount-Cloud"}) as client:
        response = await client.get(f"https://qt.gtimg.cn/q={prefix}{symbol}")
        response.raise_for_status()
    fields = response.text.split('="', 1)[-1].rstrip('";').split("~")
    if len(fields) < 5 or not fields[3]:
        raise RuntimeError("Tencent returned no quote")
    price = float(fields[3])
    previous_close = float(fields[4]) if fields[4] else None
    return {"price": price, "source": "tencent", "previous_close": previous_close,
            "day_change": price - previous_close if previous_close is not None else None}


async def _fetch_cn_fund(symbol: str) -> dict[str, float | str | None]:
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "BeeCount-Cloud"}) as client:
        response = await client.get(f"https://fund.eastmoney.com/pingzhongdata/{quote(symbol, safe='')}.js")
        response.raise_for_status()
    match = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\])\s*;", response.text, re.S)
    if not match:
        raise RuntimeError("fund provider returned no quote")
    import json
    trend = json.loads(match.group(1))
    if not trend:
        raise RuntimeError("fund provider returned empty history")
    price = float(trend[-1]["y"])
    previous_close = float(trend[-2]["y"]) if len(trend) > 1 else None
    result: dict[str, float | str | None] = {
        "price": 1.0 if re.search(r"var\s+ishb\s*=\s*true", response.text) else price,
        "source": "eastmoney_fund", "previous_close": previous_close,
        "day_change": price - previous_close if previous_close is not None else None,
    }
    # Money funds publish daily income per 10,000 shares rather than a useful
    # NAV change.  The caller scales this by the confirmed share quantity.
    income_match = re.search(r"Data_millionCopiesIncome\s*=\s*(\[.*?\])\s*;", response.text, re.S)
    if income_match:
        income_trend = json.loads(income_match.group(1))
        if income_trend:
            result["daily_income_per_10000"] = float(income_trend[-1][1])
    return result

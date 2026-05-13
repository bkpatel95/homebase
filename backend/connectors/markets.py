"""Markets connector — Stooq for indices, CoinGecko for crypto."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import ConfigField, Connector

STOOQ_INDEXES = [
    {"id": "sp500",  "symbol": "^SPX",  "label": "S&P 500"},
    {"id": "nasdaq", "symbol": "^NDQ",  "label": "NASDAQ"},
    {"id": "dow",    "symbol": "^DJI",  "label": "Dow Jones"},
]

COINGECKO_COINS = [
    {"id": "btc", "coingecko_id": "bitcoin", "label": "Bitcoin", "symbol": "BTC-USD"},
]

STOOQ_BASE = "https://stooq.com/q/l/"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


async def _stooq_one(client: httpx.AsyncClient, symbol: str) -> dict[str, Any]:
    sym = symbol.lstrip("^").lower()
    if symbol.startswith("^"):
        sym = "^" + sym
    try:
        r = await client.get(
            STOOQ_BASE,
            params={"s": sym, "i": "d", "f": "sd2t2ohlcv", "h": "", "d2": ""},
        )
        r.raise_for_status()
        lines = [ln.strip() for ln in r.text.strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return {"error": "no rows"}
        last_row = lines[-1].split(",")
        if len(last_row) < 7 or last_row[6] in ("", "N/D"):
            return {"error": "no close in last row"}
        last_close = float(last_row[6])
        last_open = float(last_row[3])
        prev = last_open
        change = last_close - prev
        pct = (change / prev * 100) if prev else None
        return {
            "price": last_close,
            "prev_close": prev,
            "change": change,
            "pct_change": pct,
            "currency": "USD",
            "as_of": last_row[1] if len(last_row) > 1 else None,
        }
    except Exception as e:
        return {"error": str(e)}


async def _coingecko_batch(client: httpx.AsyncClient, coins: list[dict]) -> dict[str, dict[str, Any]]:
    if not coins:
        return {}
    ids = ",".join(c["coingecko_id"] for c in coins)
    try:
        r = await client.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {c["coingecko_id"]: {"error": str(e)} for c in coins}

    out: dict[str, dict[str, Any]] = {}
    for c in coins:
        entry = data.get(c["coingecko_id"]) or {}
        price = entry.get("usd")
        pct = entry.get("usd_24h_change")
        if price is None:
            out[c["coingecko_id"]] = {"error": "not in response"}
        else:
            prev = price / (1 + pct / 100) if pct else price
            out[c["coingecko_id"]] = {
                "price": float(price),
                "prev_close": float(prev),
                "change": float(price - prev),
                "pct_change": float(pct) if pct is not None else None,
                "currency": "USD",
            }
    return out


class MarketsConnector(Connector):
    id = "markets"
    name = "Markets"
    description = "S&P / NASDAQ / Dow via Stooq, BTC via CoinGecko. No auth required."
    icon = "$"
    category = "data"
    widget_ids = ("markets",)
    config_schema = (
        ConfigField(
            name="extra_tickers", label="Extra tickers",
            help="Comma-separated Stooq symbols (e.g. ^FTSE,^VIX). Optional.",
            placeholder="^FTSE,^VIX",
            env_fallback="MARKETS_EXTRA",
        ),
        ConfigField(
            name="timeout", label="HTTP timeout (seconds)", type="number",
            default="5.0", env_fallback="MARKETS_TIMEOUT",
        ),
    )

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        timeout = _to_float(config.get("timeout"), 5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(STOOQ_BASE, params={"s": "^spx", "i": "d", "f": "sd2t2c"})
            if r.status_code >= 400:
                return {"ok": False, "detail": f"Stooq HTTP {r.status_code}"}
            return {"ok": True, "detail": "Stooq reachable"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        timeout = _to_float(config.get("timeout"), 5.0)
        extras = [t.strip() for t in (config.get("extra_tickers") or "").split(",") if t.strip()]

        tickers = list(STOOQ_INDEXES)
        extra_specs = [{"id": s.lower().lstrip("^"), "symbol": s, "label": s} for s in extras]

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            crypto_task = _coingecko_batch(client, COINGECKO_COINS)
            index_results: list[dict[str, Any]] = []
            for i, spec in enumerate(tickers + extra_specs):
                if i > 0:
                    await asyncio.sleep(0.15)
                index_results.append(await _stooq_one(client, spec["symbol"]))
            crypto_map = await crypto_task

        out: list[dict[str, Any]] = []
        for spec, snap in zip(tickers + extra_specs, index_results):
            out.append({**spec, **snap})
        for spec in COINGECKO_COINS:
            snap = crypto_map.get(spec["coingecko_id"], {})
            out.append({"id": spec["id"], "symbol": spec["symbol"], "label": spec["label"], **snap})

        primary = next((t for t in out if t["id"] == "sp500" and "price" in t), None)
        return {"markets": {
            "available": any("price" in t for t in out),
            "tickers": out,
            "headline_symbol": "sp500",
            "headline_pct": primary["pct_change"] if primary else None,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }}


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = MarketsConnector()

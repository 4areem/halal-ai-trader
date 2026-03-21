"""Trade execution via Alpaca API."""

import json
from datetime import datetime

import requests

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type": "application/json",
    }


def get_account() -> dict:
    """Fetch account info (balance, buying power, etc.)."""
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_positions() -> list[dict]:
    """Fetch all open positions."""
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_position(symbol: str) -> dict | None:
    """Fetch a single position by symbol."""
    try:
        resp = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions/{symbol}", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError:
        return None


def submit_order(
    symbol: str,
    qty: int | None = None,
    notional: float | None = None,
    side: str = "buy",
    order_type: str = "limit",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict:
    """Submit an order to Alpaca."""
    payload = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if qty is not None:
        payload["qty"] = str(qty)
    if notional is not None:
        payload["notional"] = str(notional)
    if limit_price is not None:
        payload["limit_price"] = str(limit_price)

    resp = requests.post(
        f"{ALPACA_BASE_URL}/v2/orders",
        headers=_headers(),
        data=json.dumps(payload),
    )
    resp.raise_for_status()
    return resp.json()


def get_orders(status: str = "open") -> list[dict]:
    """Fetch orders by status."""
    resp = requests.get(
        f"{ALPACA_BASE_URL}/v2/orders",
        headers=_headers(),
        params={"status": status},
    )
    resp.raise_for_status()
    return resp.json()


def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 30) -> list[dict]:
    """Fetch historical bars from Alpaca data API."""
    resp = requests.get(
        "https://data.alpaca.markets/v2/stocks/{}/bars".format(symbol),
        headers=_headers(),
        params={"timeframe": timeframe, "limit": limit},
    )
    resp.raise_for_status()
    return resp.json().get("bars", [])


def get_clock() -> dict:
    """Fetch market clock (is_open, next_open, next_close)."""
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/clock", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_latest_quote(symbol: str) -> dict:
    """Fetch latest quote for a symbol."""
    resp = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest",
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json().get("quote", {})


def get_latest_quotes(symbols: list[str]) -> dict:
    """Fetch latest quotes for multiple symbols."""
    resp = requests.get(
        "https://data.alpaca.markets/v2/stocks/quotes/latest",
        headers=_headers(),
        params={"symbols": ",".join(symbols)},
    )
    resp.raise_for_status()
    return resp.json().get("quotes", {})


def get_snapshot(symbol: str) -> dict:
    """Fetch snapshot (latest trade, quote, minute/daily bar) for a symbol."""
    resp = requests.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot",
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


def cancel_all_orders() -> None:
    """Cancel all open orders."""
    resp = requests.delete(f"{ALPACA_BASE_URL}/v2/orders", headers=_headers())
    resp.raise_for_status()

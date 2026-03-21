"""Watchlist management per agents.md Section 6."""

import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlist.json")
REVIEW_PATH = os.path.join(DATA_DIR, "review_list.json")
REJECTED_PATH = os.path.join(DATA_DIR, "rejected.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(path: str) -> list[dict]:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def _save_json(path: str, data: list[dict]) -> None:
    _ensure_data_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_watchlist() -> list[dict]:
    return _load_json(WATCHLIST_PATH)


def save_watchlist(stocks: list[dict]) -> None:
    _save_json(WATCHLIST_PATH, stocks)


def load_review_list() -> list[dict]:
    return _load_json(REVIEW_PATH)


def save_review_list(stocks: list[dict]) -> None:
    _save_json(REVIEW_PATH, stocks)


def load_rejected() -> list[dict]:
    return _load_json(REJECTED_PATH)


def save_rejected(stocks: list[dict]) -> None:
    _save_json(REJECTED_PATH, stocks)


def add_to_watchlist(stock: dict) -> None:
    """Add a stock to the active watchlist if not already present."""
    watchlist = load_watchlist()
    tickers = {s["ticker"] for s in watchlist}
    if stock["ticker"] not in tickers:
        watchlist.append(stock)
        save_watchlist(watchlist)


def remove_from_watchlist(ticker: str) -> None:
    """Remove a stock from the active watchlist."""
    watchlist = load_watchlist()
    watchlist = [s for s in watchlist if s["ticker"] != ticker]
    save_watchlist(watchlist)


def make_stock_entry(
    ticker: str,
    name: str,
    sector: str,
    shariah_status: str,
    debt_ratio: float | None = None,
    securities_ratio: float | None = None,
    impure_revenue: float | None = None,
    purification_rate: float = 0.0,
    notes: str = "",
) -> dict:
    """Create a standardized watchlist entry."""
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "shariah_status": shariah_status,
        "screening_date": datetime.now().strftime("%Y-%m-%d"),
        "debt_ratio": debt_ratio,
        "securities_ratio": securities_ratio,
        "impure_revenue": impure_revenue,
        "purification_rate": purification_rate,
        "notes": notes,
    }

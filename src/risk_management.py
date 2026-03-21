"""Risk management rules per agents.md Section 3."""

from dataclasses import dataclass

from src.config import (
    MAX_POSITION_PCT,
    MAX_POSITIONS,
    MIN_POSITION_USD,
    CASH_RESERVE_PCT,
    STOP_LOSS_PCT,
    TRAILING_STOP_ACTIVATION,
    TRAILING_STOP_PCT,
    TIME_STOP_DAYS,
    MAX_SECTOR_PCT,
    DRAWDOWN_HALT_PCT,
)


@dataclass
class RiskCheckResult:
    passed: bool
    position_size_ok: bool
    position_count_ok: bool
    cash_reserve_ok: bool
    sector_exposure_ok: bool
    drawdown_ok: bool
    notes: str = ""


def check_position_size(trade_amount: float, portfolio_value: float) -> bool:
    """Position must be between MIN_POSITION_USD and MAX_POSITION_PCT of portfolio."""
    if trade_amount < MIN_POSITION_USD:
        return False
    return trade_amount <= portfolio_value * MAX_POSITION_PCT


def check_position_count(current_positions: int) -> bool:
    return current_positions < MAX_POSITIONS


def check_cash_reserve(
    cash_after_trade: float, portfolio_value: float
) -> bool:
    return cash_after_trade >= portfolio_value * CASH_RESERVE_PCT


def check_sector_exposure(
    sector_value_after: float, portfolio_value: float
) -> bool:
    return sector_value_after <= portfolio_value * MAX_SECTOR_PCT


def check_drawdown(current_value: float, peak_value: float) -> bool:
    """Return False if portfolio is in drawdown halt mode."""
    if peak_value == 0:
        return True
    drawdown = (peak_value - current_value) / peak_value
    return drawdown < DRAWDOWN_HALT_PCT


def check_stop_loss(current_price: float, entry_price: float) -> bool:
    """Return True if stop-loss is triggered (should sell)."""
    return current_price <= entry_price * (1 - STOP_LOSS_PCT)


def check_trailing_stop(
    current_price: float, entry_price: float, peak_price: float
) -> bool:
    """Return True if trailing stop is triggered (should sell)."""
    gain_from_entry = (peak_price - entry_price) / entry_price
    if gain_from_entry < TRAILING_STOP_ACTIVATION:
        return False
    return current_price <= peak_price * (1 - TRAILING_STOP_PCT)


def check_time_stop(holding_days: int, pnl_pct: float) -> bool:
    """Return True if time stop suggests re-evaluation (position gone nowhere)."""
    return holding_days >= TIME_STOP_DAYS and abs(pnl_pct) < 0.03


def run_risk_check(
    trade_amount: float,
    portfolio_value: float,
    cash_after_trade: float,
    current_positions: int,
    sector_value_after: float,
    current_value: float,
    peak_value: float,
) -> RiskCheckResult:
    """Run all pre-trade risk checks."""
    pos_size = check_position_size(trade_amount, portfolio_value)
    pos_count = check_position_count(current_positions)
    cash_ok = check_cash_reserve(cash_after_trade, portfolio_value)
    sector_ok = check_sector_exposure(sector_value_after, portfolio_value)
    dd_ok = check_drawdown(current_value, peak_value)

    passed = all([pos_size, pos_count, cash_ok, sector_ok, dd_ok])

    notes_parts = []
    if not pos_size:
        notes_parts.append("Position size out of range")
    if not pos_count:
        notes_parts.append("Max positions reached")
    if not cash_ok:
        notes_parts.append("Cash reserve too low")
    if not sector_ok:
        notes_parts.append("Sector over-concentrated")
    if not dd_ok:
        notes_parts.append("Portfolio in drawdown halt")

    return RiskCheckResult(
        passed=passed,
        position_size_ok=pos_size,
        position_count_ok=pos_count,
        cash_reserve_ok=cash_ok,
        sector_exposure_ok=sector_ok,
        drawdown_ok=dd_ok,
        notes="; ".join(notes_parts),
    )

"""Main trading session runner per agents.md Section 8.

Orchestrates the full trading workflow:
  1. Session Startup  — account status, positions, market check
  2. Analysis Phase   — news pipeline, stop-loss checks
  3. Decision Phase   — generate trade decision logs
  4. Execution Phase  — place orders (sells first, then buys)
  5. Session Closeout — log everything

Usage:
  python -m src.runner          # Dry run (default)
  python -m src.runner --live   # Live execution
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from src.config import (
    MAX_POSITION_PCT,
    MAX_POSITIONS,
    MIN_POSITION_USD,
    CASH_RESERVE_PCT,
    STOP_LOSS_PCT,
    MAX_SECTOR_PCT,
    DRAWDOWN_HALT_PCT,
    TIME_STOP_DAYS,
)
from src.trade_executor import (
    get_account,
    get_positions,
    get_clock,
    get_snapshot,
    get_latest_quotes,
    submit_order,
)
from src.risk_management import (
    check_stop_loss,
    check_trailing_stop,
    check_time_stop,
    run_risk_check,
)
from src.news_analysis import (
    fetch_watchlist_news,
    TickerAnalysis,
    Sentiment,
    Confidence,
    aggregate_sentiment,
    analyze_ticker_with_llm,
    apply_llm_results,
    save_analysis_results,
    print_signal_report,
    SENTIMENT_SCORES,
)
from src.watchlist import load_watchlist
from src.logger import log_trade_decision, log_session, log_performance

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeDecision:
    """Structured trade decision log per agents.md Section 5.3."""
    date: str
    ticker: str
    action: str  # BUY / SELL / HOLD / NO_ACTION
    conviction: str  # HIGH / MEDIUM / LOW

    # Shariah check
    shariah_status: str = "COMPLIANT"
    purification_rate: float = 0.0

    # Risk check
    position_size_usd: float = 0.0
    position_size_pct: float = 0.0
    current_positions: int = 0
    cash_after_trade_pct: float = 0.0
    sector_exposure_pct: float = 0.0
    risk_passed: bool = True
    risk_notes: str = ""

    # Thesis
    news_catalyst: str = ""
    signal_strength: float = 0.0
    key_risk: str = ""

    # Execution details
    order_type: str = ""
    limit_price: float = 0.0
    quantity: int = 0
    executed: bool = False
    execution_notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def format_log(self) -> str:
        """Format as the structured log from agents.md 5.3."""
        lines = [
            "=== TRADE DECISION LOG ===",
            f"Date: {self.date}",
            f"Ticker: {self.ticker}",
            f"Action: {self.action}",
            f"Conviction: {self.conviction}",
            "",
            "--- Shariah Check ---",
            f"Overall Shariah Status: {self.shariah_status}",
            f"Purification Rate: {self.purification_rate:.1%}",
            "",
            "--- Risk Check ---",
            f"Position Size: ${self.position_size_usd:,.0f} ({self.position_size_pct:.1%} of portfolio)",
            f"Current Open Positions: {self.current_positions}/{MAX_POSITIONS}",
            f"Cash After Trade: {self.cash_after_trade_pct:.1%} of portfolio",
            f"Sector Exposure After Trade: {self.sector_exposure_pct:.1%}",
            f"Risk Status: {'PASS' if self.risk_passed else 'FAIL — ' + self.risk_notes}",
            "",
            "--- Thesis ---",
            f"News Catalyst: {self.news_catalyst}",
            f"Signal Strength: {self.signal_strength:+.1f}",
            f"Key Risk: {self.key_risk}",
            "",
            "--- Decision ---",
            f"Final Action: {self.action}",
        ]
        if self.order_type:
            lines.append(f"Order Type: {self.order_type} at ${self.limit_price:,.2f}")
            lines.append(f"Quantity: {self.quantity} shares")
        if self.execution_notes:
            lines.append(f"Notes: {self.execution_notes}")
        lines.append("===")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 1: Session Startup (agents.md 8.1)
# ---------------------------------------------------------------------------

def _mode_label(live: bool, auto: bool) -> str:
    """Return the execution mode label for display and logging."""
    if not live:
        return "DRY_RUN"
    return "LIVE_AUTO" if auto else "LIVE_CONFIRM"


def session_startup(live: bool = False, auto: bool = False, use_ai: bool = False) -> dict:
    """Fetch account, positions, market status. Returns session context dict."""
    mode = _mode_label(live, auto)
    analysis_mode = "AI (Claude)" if use_ai else "Rules-based"
    print("=" * 70)
    print("HALAL AI TRADER — SESSION START")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode:      {mode}")
    print(f"Analysis:  {analysis_mode}")
    print("=" * 70)

    # Account
    account = get_account()
    equity = float(account["equity"])
    cash = float(account["cash"])
    buying_power = float(account["buying_power"])

    print(f"\n--- Account ---")
    print(f"  Equity:       ${equity:>12,.2f}")
    print(f"  Cash:         ${cash:>12,.2f}")
    print(f"  Buying Power: ${buying_power:>12,.2f}")
    print(f"  Cash Reserve: {cash / equity:.1%}  (min: {CASH_RESERVE_PCT:.0%})")

    # Positions
    positions = get_positions()
    print(f"\n--- Positions ({len(positions)}/{MAX_POSITIONS}) ---")
    total_unrealized = 0.0
    position_map = {}
    for p in positions:
        sym = p["symbol"]
        qty = int(float(p["qty"]))
        mv = float(p["market_value"])
        entry = float(p["avg_entry_price"])
        current = float(p["current_price"])
        upl = float(p["unrealized_pl"])
        upl_pct = float(p["unrealized_plpc"]) * 100
        total_unrealized += upl
        position_map[sym] = p
        print(f"  {sym:6s}  {qty:>4} shares  entry ${entry:>8.2f}  "
              f"now ${current:>8.2f}  P&L ${upl:>+9.2f} ({upl_pct:>+.1f}%)")
    if not positions:
        print("  (no open positions)")
    else:
        print(f"  Total unrealized P&L: ${total_unrealized:>+,.2f}")

    # Market clock
    clock = get_clock()
    market_open = clock["is_open"]
    print(f"\n--- Market Status ---")
    print(f"  Market open: {market_open}")
    if not market_open:
        print(f"  Next open:   {clock['next_open']}")

    # SPY snapshot for market regime
    spy_data = {}
    try:
        snap = get_snapshot("SPY")
        spy_trade = snap.get("latestTrade", {})
        spy_daily = snap.get("dailyBar", {})
        spy_prev = snap.get("prevDailyBar", {})
        spy_price = spy_trade.get("p", 0)
        spy_prev_close = spy_prev.get("c", 0) if spy_prev else 0
        spy_change_pct = ((spy_price - spy_prev_close) / spy_prev_close * 100) if spy_prev_close else 0

        spy_data = {
            "price": spy_price,
            "prev_close": spy_prev_close,
            "change_pct": round(spy_change_pct, 2),
            "daily_high": spy_daily.get("h", 0),
            "daily_low": spy_daily.get("l", 0),
        }
        print(f"  SPY:         ${spy_price:,.2f} ({spy_change_pct:+.2f}%)")

        # Simple regime detection
        if spy_change_pct > 1:
            regime = "BULLISH"
        elif spy_change_pct < -1:
            regime = "BEARISH"
        else:
            regime = "SIDEWAYS"
        spy_data["regime"] = regime
        print(f"  Regime:      {regime}")
    except Exception as e:
        print(f"  SPY data unavailable: {e}")
        spy_data = {"price": 0, "regime": "UNKNOWN"}

    # Build context
    ctx = {
        "account": account,
        "equity": equity,
        "cash": cash,
        "buying_power": buying_power,
        "positions": positions,
        "position_map": position_map,
        "num_positions": len(positions),
        "market_open": market_open,
        "spy": spy_data,
        "peak_equity": equity,  # TODO: track historical peak
    }

    # Log session start
    log_session({
        "phase": "startup",
        "mode": mode,
        "analysis": analysis_mode,
        "equity": equity,
        "cash": cash,
        "buying_power": buying_power,
        "positions_count": len(positions),
        "spy": spy_data,
        "market_open": market_open,
    })

    return ctx


# ---------------------------------------------------------------------------
# Phase 2: Analysis (agents.md 8.2)
# ---------------------------------------------------------------------------

def _auto_classify_item(item):
    """Rules-based sentiment classification. At runtime, the AI agent
    would use build_analysis_prompt() for deeper analysis."""
    text = (item.headline + " " + item.summary).lower()

    strong_neg = ['crash', 'plunge', 'scandal', 'fraud', 'indicted', 'smuggling',
                  'collapse', 'death cross', 'bankruptcy', 'sec investigation',
                  'lawsuit', 'misled investors', 'liable', 'safety concern', 'recall',
                  'criminal', 'sec charges']
    mild_neg = ['drops', 'falling', 'decline', 'downgrade', 'concern', 'risk',
                'bear', 'sell-off', 'selloff', 'fears', 'hammer', 'pain', 'warning',
                'slump', 'weak', 'miss', 'cut']
    strong_pos = ['fda approval', 'earnings beat', 'record revenue', 'breakthrough',
                  'major contract', 'acquisition complete', 'best ever',
                  'weight loss', 'new rally', 'blowout', 'soars', 'surge']
    mild_pos = ['rises', 'gains', 'positive', 'growth', 'expanding', 'approval',
                'launch', 'partnership', 'raises price target', 'upgrade',
                'rally', 'backs', 'targets', 'optimistic', 'wins', 'maintains']

    score = 0
    for kw in strong_neg:
        if kw in text:
            score -= 2
    for kw in mild_neg:
        if kw in text:
            score -= 1
    for kw in strong_pos:
        if kw in text:
            score += 2
    for kw in mild_pos:
        if kw in text:
            score += 1

    # Whale activity / market roundups are noise
    if 'whale' in text or 'triple witching' in text or "what's moving markets" in text:
        item.sentiment = Sentiment.NEUTRAL
        item.confidence = Confidence.LOW
        item.already_priced_in = True
        return item

    if score >= 3:
        item.sentiment = Sentiment.STRONG_POSITIVE
        item.confidence = Confidence.HIGH
    elif score >= 1:
        item.sentiment = Sentiment.MILD_POSITIVE
        item.confidence = Confidence.MEDIUM
    elif score == 0:
        item.sentiment = Sentiment.NEUTRAL
        item.confidence = Confidence.LOW
    elif score >= -2:
        item.sentiment = Sentiment.MILD_NEGATIVE
        item.confidence = Confidence.MEDIUM
    else:
        item.sentiment = Sentiment.STRONG_NEGATIVE
        item.confidence = Confidence.HIGH

    return item


def analysis_phase(ctx: dict, use_ai: bool = False) -> list[TickerAnalysis]:
    """Run news analysis pipeline on the full watchlist."""
    print(f"\n{'=' * 70}")
    print(f"ANALYSIS PHASE {'(AI-powered)' if use_ai else '(rules-based)'}")
    print("=" * 70)

    watchlist = load_watchlist()
    name_map = {s["ticker"]: s["name"] for s in watchlist}

    # Fetch and classify news
    news = fetch_watchlist_news(watchlist, hours_back=72)

    # First pass: rules-based classification for all tickers (fast baseline)
    for ticker_items in news.values():
        for item in ticker_items:
            _auto_classify_item(item)

    # Identify tickers with enough news to justify AI analysis
    ai_candidates = []
    if use_ai:
        for entry in watchlist:
            ticker = entry["ticker"]
            items = news.get(ticker, [])
            if items:  # Only send tickers with news to the LLM
                ai_candidates.append(ticker)
        print(f"  AI analysis queued for {len(ai_candidates)} tickers with news")

    # AI pass: run LLM analysis on tickers that have news
    ai_results: dict[str, dict] = {}
    if use_ai and ai_candidates:
        print(f"\n--- Running Claude analysis ---")
        for ticker in ai_candidates:
            items = news.get(ticker, [])
            name = name_map.get(ticker, ticker)
            print(f"  Analyzing {ticker} ({len(items)} articles)...", end=" ")
            result = analyze_ticker_with_llm(ticker, name, items)
            if result:
                ai_results[ticker] = result
            else:
                print(f"    (fallback to rules-based)")
        print(f"  AI completed: {len(ai_results)}/{len(ai_candidates)} tickers\n")

    results = []
    for entry in watchlist:
        ticker = entry["ticker"]
        items = news.get(ticker, [])

        # Use AI results if available, otherwise use rules-based
        if ticker in ai_results:
            llm_data = ai_results[ticker]
            (overall_sentiment, conf, signal_strength,
             reasoning, contrarian) = apply_llm_results(items, llm_data)

            # Prefix reasoning to show it came from AI
            reasoning = f"[AI] {reasoning}"
            if contrarian:
                reasoning += f" | CONTRARIAN: {contrarian}"
        else:
            # Rules-based path (items already classified by _auto_classify_item)
            overall_sentiment, signal_strength = aggregate_sentiment(items)
            contrarian = None

            if items:
                pos_n = sum(1 for i in items if SENTIMENT_SCORES[i.sentiment] > 0)
                neg_n = sum(1 for i in items if SENTIMENT_SCORES[i.sentiment] < 0)
                neu_n = sum(1 for i in items if SENTIMENT_SCORES[i.sentiment] == 0)
                top = max(items, key=lambda x: abs(SENTIMENT_SCORES[x.sentiment]))
                reasoning = (f"{len(items)} articles: {pos_n}+, {neg_n}-, {neu_n} neutral. "
                             f"Top: '{top.headline[:80]}'")
            else:
                reasoning = "No news in last 72 hours."

            if len(items) >= 3 and abs(signal_strength) >= 1.0:
                conf = Confidence.HIGH
            elif len(items) >= 2 and abs(signal_strength) >= 0.5:
                conf = Confidence.MEDIUM
            else:
                conf = Confidence.LOW

        actionable = (
            abs(signal_strength) >= 0.5
            and overall_sentiment != Sentiment.NEUTRAL
            and len(items) > 0
        )

        if signal_strength >= 1.0:
            action = "BUY_SIGNAL"
        elif signal_strength >= 0.5:
            action = "WATCH_BUY"
        elif signal_strength <= -1.0:
            action = "SELL_SIGNAL"
        elif signal_strength <= -0.5:
            action = "WATCH_SELL"
        else:
            action = "NO_ACTION"

        results.append(TickerAnalysis(
            ticker=ticker,
            company_name=name_map.get(ticker, ticker),
            items=items,
            overall_sentiment=overall_sentiment,
            overall_confidence=conf,
            actionable=actionable,
            signal_strength=signal_strength,
            reasoning=reasoning,
            recommended_action=action,
        ))

    # Save and print
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    save_analysis_results(results, ts)
    print_signal_report(results)

    return results


# ---------------------------------------------------------------------------
# Phase 2b: Position checks (stop-loss, time stop)
# ---------------------------------------------------------------------------

def check_existing_positions(ctx: dict) -> list[TradeDecision]:
    """Check all positions for stop-loss and time-stop triggers."""
    decisions = []
    positions = ctx["positions"]
    equity = ctx["equity"]

    if not positions:
        return decisions

    print(f"\n--- Position Health Checks ---")
    for p in positions:
        sym = p["symbol"]
        entry = float(p["avg_entry_price"])
        current = float(p["current_price"])
        upl_pct = float(p["unrealized_plpc"])
        mv = float(p["market_value"])

        # Hard stop-loss: -8%
        if check_stop_loss(current, entry):
            loss_pct = (current - entry) / entry
            print(f"  STOP-LOSS TRIGGERED: {sym} at {loss_pct:.1%} "
                  f"(entry ${entry:.2f} -> ${current:.2f})")

            decisions.append(TradeDecision(
                date=datetime.now().strftime("%Y-%m-%d"),
                ticker=sym,
                action="SELL",
                conviction="HIGH",
                news_catalyst=f"Hard stop-loss triggered at {loss_pct:.1%} (threshold: -{STOP_LOSS_PCT:.0%})",
                signal_strength=-2.0,
                key_risk="Continued decline",
                order_type="MARKET",
                limit_price=current,
                quantity=int(float(p["qty"])),
                position_size_usd=mv,
                position_size_pct=mv / equity if equity else 0,
                execution_notes="Stop-loss sell — no discretion, rule-based exit",
            ))
            continue

        # Time stop: >15 days and <3% movement
        # NOTE: Alpaca doesn't directly expose holding period in position data,
        # so we'd need to track entry dates separately. For now, flag positions
        # that are flat (within +/- 3%).
        if abs(upl_pct) < 0.03:
            print(f"  TIME-STOP CANDIDATE: {sym} at {upl_pct:+.1%} — flat, needs thesis review")
        else:
            direction = "up" if upl_pct > 0 else "down"
            print(f"  {sym}: {upl_pct:+.1%} ({direction}) — OK")

    return decisions


# ---------------------------------------------------------------------------
# Phase 3: Decision (agents.md 5.3)
# ---------------------------------------------------------------------------

def decision_phase(
    ctx: dict,
    analysis_results: list[TickerAnalysis],
    position_decisions: list[TradeDecision],
) -> list[TradeDecision]:
    """Generate trade decisions for all actionable signals."""
    print(f"\n{'=' * 70}")
    print("DECISION PHASE")
    print("=" * 70)

    decisions = list(position_decisions)  # start with stop-loss sells
    equity = ctx["equity"]
    cash = ctx["cash"]
    num_positions = ctx["num_positions"]
    position_map = ctx["position_map"]
    peak_equity = ctx["peak_equity"]

    watchlist = load_watchlist()
    sector_map = {s["ticker"]: s["sector"] for s in watchlist}
    shariah_map = {s["ticker"]: s for s in watchlist}

    # Calculate current sector exposure
    sector_values: dict[str, float] = {}
    for p in ctx["positions"]:
        sym = p["symbol"]
        mv = float(p["market_value"])
        sec = sector_map.get(sym, "Unknown")
        sector_values[sec] = sector_values.get(sec, 0) + mv

    # Drawdown check
    in_drawdown_halt = False
    if peak_equity > 0:
        drawdown = (peak_equity - equity) / peak_equity
        if drawdown >= DRAWDOWN_HALT_PCT:
            in_drawdown_halt = True
            print(f"\n  DRAWDOWN HALT: Portfolio down {drawdown:.1%} from peak. NO NEW BUYS.")

    # Regime-based capital deployment limits (agents.md Section 7)
    regime = ctx.get("spy", {}).get("regime", "UNKNOWN")
    if regime == "BULLISH":
        max_deploy_pct = 0.70   # Use 60-70% of capital
        regime_label = "BULL — deploy up to 70%"
    elif regime == "SIDEWAYS" or regime == "UNKNOWN":
        max_deploy_pct = 0.50   # Use 40-50% of capital
        regime_label = "SIDEWAYS — deploy up to 50%"
    else:  # BEARISH
        max_deploy_pct = 0.30   # Use 20-30% of capital
        regime_label = "BEAR — deploy up to 30%"

    # Current deployment = equity in positions
    current_deployed = sum(float(p["market_value"]) for p in ctx["positions"])
    current_deploy_pct = current_deployed / equity if equity else 0
    max_deploy_usd = equity * max_deploy_pct
    remaining_deploy_budget = max(0, max_deploy_usd - current_deployed)

    print(f"\n--- Regime Capital Limits (agents.md §7) ---")
    print(f"  Market regime:     {regime}")
    print(f"  Guideline:         {regime_label}")
    print(f"  Currently deployed: ${current_deployed:,.0f} ({current_deploy_pct:.0%})")
    print(f"  Max deployment:     ${max_deploy_usd:,.0f} ({max_deploy_pct:.0%})")
    print(f"  Remaining budget:   ${remaining_deploy_budget:,.0f}")

    # Count sells from position decisions to free up slots
    sell_count = sum(1 for d in decisions if d.action == "SELL")

    # Process actionable signals
    actionable = [r for r in analysis_results if r.actionable]
    actionable_sorted = sorted(actionable, key=lambda r: abs(r.signal_strength), reverse=True)

    buy_candidates = []
    today = datetime.now().strftime("%Y-%m-%d")

    for result in actionable_sorted:
        ticker = result.ticker
        held = ticker in position_map

        # --- SELL signals on positions we hold ---
        if result.signal_strength <= -0.5 and held:
            # Don't double-count if already flagged by stop-loss
            already_selling = any(d.ticker == ticker and d.action == "SELL" for d in decisions)
            if already_selling:
                continue

            p = position_map[ticker]
            mv = float(p["market_value"])
            qty = int(float(p["qty"]))
            current = float(p["current_price"])

            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="SELL",
                conviction="MEDIUM" if result.signal_strength <= -1.0 else "LOW",
                shariah_status=shariah_map.get(ticker, {}).get("shariah_status", "COMPLIANT"),
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                key_risk="Thesis may still be intact — news-driven sell",
                order_type="LIMIT",
                limit_price=round(current * 0.998, 2),  # slight discount to fill
                quantity=qty,
                position_size_usd=mv,
                position_size_pct=mv / equity if equity else 0,
                execution_notes=f"News-driven sell signal ({result.signal_strength:+.1f})",
            ))
            continue

        # --- BUY signals for stocks we don't hold ---
        if result.signal_strength >= 0.5 and not held:
            buy_candidates.append(result)

        # --- HOLD for stocks we hold with positive/neutral signal ---
        if held and result.signal_strength > -0.5:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="HOLD",
                conviction="MEDIUM",
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                execution_notes="Thesis intact, holding position",
            ))

    # --- Process BUY candidates ---
    print(f"\n--- Buy Candidates: {len(buy_candidates)} ---")

    # Estimate cash freed by sells
    sell_cash = sum(d.position_size_usd for d in decisions if d.action == "SELL")
    available_cash = cash + sell_cash
    effective_positions = num_positions - sell_count

    # Track total new deployment against regime budget
    total_new_deployment = 0.0

    for result in buy_candidates:
        ticker = result.ticker
        wl_entry = shariah_map.get(ticker, {})
        sector = sector_map.get(ticker, "Unknown")

        # Conviction filter (agents.md 5.3)
        if result.signal_strength >= 1.0 and result.overall_confidence in (Confidence.HIGH, Confidence.MEDIUM):
            conviction = "HIGH"
            size_mult = 1.0
        elif result.signal_strength >= 0.5:
            conviction = "MEDIUM"
            size_mult = 0.5
        else:
            conviction = "LOW"
            # LOW conviction = watchlist only, don't trade
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction="LOW",
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                execution_notes="Low conviction — watchlist only, no trade",
            ))
            continue

        # Regime capital limit check (agents.md Section 7)
        if total_new_deployment >= remaining_deploy_budget:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                risk_passed=False,
                risk_notes=(f"Regime budget exhausted: {regime} regime allows "
                            f"{max_deploy_pct:.0%} deployment (${max_deploy_usd:,.0f}), "
                            f"already deploying ${current_deployed + total_new_deployment:,.0f}"),
                execution_notes=f"Blocked by {regime} regime capital limit",
            ))
            continue

        # Drawdown halt check
        if in_drawdown_halt:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                risk_passed=False,
                risk_notes="Portfolio in drawdown halt — no new buys",
                execution_notes="Blocked by drawdown halt",
            ))
            continue

        # Position count check
        if effective_positions >= MAX_POSITIONS:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                risk_passed=False,
                risk_notes=f"Max positions reached ({MAX_POSITIONS})",
                execution_notes="Blocked by position count limit",
            ))
            continue

        # Calculate position size (capped by regime budget)
        max_size = equity * MAX_POSITION_PCT * size_mult
        regime_remaining = remaining_deploy_budget - total_new_deployment
        trade_amount = min(max_size, available_cash * 0.9, regime_remaining)

        # Cash reserve check
        cash_after = available_cash - trade_amount
        min_cash = equity * CASH_RESERVE_PCT
        if cash_after < min_cash:
            trade_amount = available_cash - min_cash
            if trade_amount < MIN_POSITION_USD:
                decisions.append(TradeDecision(
                    date=today,
                    ticker=ticker,
                    action="NO_ACTION",
                    conviction=conviction,
                    news_catalyst=result.reasoning[:200],
                    signal_strength=result.signal_strength,
                    risk_passed=False,
                    risk_notes=f"Insufficient cash after reserve (need ${min_cash:,.0f})",
                    execution_notes="Blocked by cash reserve requirement",
                ))
                continue

        # Min position check
        if trade_amount < MIN_POSITION_USD:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                risk_passed=False,
                risk_notes=f"Position ${trade_amount:,.0f} below minimum ${MIN_POSITION_USD}",
                execution_notes="Below minimum position size",
            ))
            continue

        # Sector exposure check
        current_sector_value = sector_values.get(sector, 0)
        sector_after = current_sector_value + trade_amount
        if sector_after > equity * MAX_SECTOR_PCT:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                risk_passed=False,
                risk_notes=f"Sector {sector} would be {sector_after / equity:.0%} (max {MAX_SECTOR_PCT:.0%})",
                execution_notes="Blocked by sector concentration limit",
            ))
            continue

        # Get current price for limit order
        try:
            quotes = get_latest_quotes([ticker])
            quote = quotes.get(ticker, {})
            ask = float(quote.get("ap", 0))
            bid = float(quote.get("bp", 0))
            # Use ask price, or midpoint if ask is zero (market closed)
            if ask > 0:
                price = ask
            elif bid > 0:
                price = bid
            else:
                # Fallback: try snapshot
                snap = get_snapshot(ticker)
                price = snap.get("latestTrade", {}).get("p", 0)
        except Exception:
            price = 0

        if price <= 0:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                risk_passed=False,
                risk_notes="Could not determine current price",
                execution_notes="Price unavailable — skipping",
            ))
            continue

        # Calculate shares
        quantity = int(trade_amount / price)
        if quantity < 1:
            quantity = 1
        actual_cost = quantity * price

        # Set limit price slightly below ask to avoid chasing
        limit_price = round(price * 0.998, 2)

        # Sleep test (agents.md 5.4): codified as a sanity check
        # "If I bought this and couldn't check for 2 weeks, would I be comfortable?"
        # For rules-based: skip if signal is based on single low-tier article
        sleep_test_pass = not (
            len(result.items) == 1
            and result.items[0].source_tier.value >= 4
        )
        if not sleep_test_pass:
            decisions.append(TradeDecision(
                date=today,
                ticker=ticker,
                action="NO_ACTION",
                conviction=conviction,
                news_catalyst=result.reasoning[:200],
                signal_strength=result.signal_strength,
                execution_notes="Failed sleep test — single low-tier source",
            ))
            continue

        # ALL CHECKS PASSED — generate buy decision
        cash_after_pct = (available_cash - actual_cost) / equity

        decisions.append(TradeDecision(
            date=today,
            ticker=ticker,
            action="BUY",
            conviction=conviction,
            shariah_status=wl_entry.get("shariah_status", "COMPLIANT"),
            purification_rate=wl_entry.get("purification_rate", 0),
            position_size_usd=actual_cost,
            position_size_pct=actual_cost / equity if equity else 0,
            current_positions=effective_positions + 1,
            cash_after_trade_pct=cash_after_pct,
            sector_exposure_pct=(current_sector_value + actual_cost) / equity if equity else 0,
            risk_passed=True,
            news_catalyst=result.reasoning[:200],
            signal_strength=result.signal_strength,
            key_risk=f"News-driven entry — could reverse",
            order_type="LIMIT",
            limit_price=limit_price,
            quantity=quantity,
            execution_notes=f"{conviction} conviction, {size_mult:.0%} size",
        ))

        # Update tracking for subsequent candidates
        available_cash -= actual_cost
        effective_positions += 1
        total_new_deployment += actual_cost
        sector_values[sector] = sector_values.get(sector, 0) + actual_cost

    # --- Log all decisions ---
    print(f"\n--- Decisions Summary ---")
    buys = [d for d in decisions if d.action == "BUY"]
    sells = [d for d in decisions if d.action == "SELL"]
    holds = [d for d in decisions if d.action == "HOLD"]
    no_actions = [d for d in decisions if d.action == "NO_ACTION"]

    print(f"  BUY:       {len(buys)}")
    print(f"  SELL:      {len(sells)}")
    print(f"  HOLD:      {len(holds)}")
    print(f"  NO ACTION: {len(no_actions)}")

    total_buy = sum(d.position_size_usd for d in buys)
    total_deploy = current_deployed + total_buy - sum(d.position_size_usd for d in sells)
    deploy_pct = total_deploy / equity if equity else 0
    print(f"\n  Regime:           {regime} ({regime_label})")
    print(f"  New buy total:    ${total_buy:,.0f}")
    print(f"  Total deployed:   ${total_deploy:,.0f} ({deploy_pct:.0%} of equity)")
    print(f"  Regime limit:     ${max_deploy_usd:,.0f} ({max_deploy_pct:.0%} of equity)")
    if deploy_pct > max_deploy_pct:
        print(f"  *** OVER REGIME LIMIT — should not happen ***")
    else:
        print(f"  Within regime guideline.")

    for d in decisions:
        if d.action in ("BUY", "SELL"):
            print(f"\n{d.format_log()}")
        elif d.action == "NO_ACTION" and d.risk_notes:
            print(f"\n  BLOCKED: {d.ticker} ({d.conviction}, signal {d.signal_strength:+.1f}) "
                  f"— {d.risk_notes}")

    return decisions


# ---------------------------------------------------------------------------
# Phase 4: Execution (agents.md 8.4)
# ---------------------------------------------------------------------------

def execution_phase(ctx: dict, decisions: list[TradeDecision], live: bool = False, auto: bool = False) -> list[dict]:
    """Execute trades. Sells first, then buys by conviction."""
    mode = _mode_label(live, auto)
    print(f"\n{'=' * 70}")
    print(f"EXECUTION PHASE ({mode})")
    print("=" * 70)

    executed_orders = []

    sells = sorted(
        [d for d in decisions if d.action == "SELL"],
        key=lambda d: d.signal_strength,  # most negative first
    )
    buys = sorted(
        [d for d in decisions if d.action == "BUY"],
        key=lambda d: -d.signal_strength,  # most positive first
    )

    # Live mode: show confirmation summary and require approval (unless auto)
    if live and not auto and (sells or buys):
        print(f"\n{'=' * 70}")
        print("ORDER CONFIRMATION — REVIEW BEFORE EXECUTION")
        print(f"{'=' * 70}")

        if sells:
            print(f"\n  SELLS ({len(sells)}):")
            print(f"  {'Ticker':<8} {'Qty':>5} {'Type':<8} {'Price':>10} {'Value':>12} {'Reason'}")
            print(f"  {'-'*8} {'-'*5} {'-'*8} {'-'*10} {'-'*12} {'-'*30}")
            for d in sells:
                print(f"  {d.ticker:<8} {d.quantity:>5} {d.order_type:<8} "
                      f"${d.limit_price:>9,.2f} ${d.position_size_usd:>11,.0f} "
                      f"{d.news_catalyst[:30]}")

        if buys:
            print(f"\n  BUYS ({len(buys)}):")
            print(f"  {'Ticker':<8} {'Qty':>5} {'Conv':<8} {'Price':>10} {'Value':>12} {'Signal':>7} {'Catalyst'}")
            print(f"  {'-'*8} {'-'*5} {'-'*8} {'-'*10} {'-'*12} {'-'*7} {'-'*30}")
            for d in buys:
                print(f"  {d.ticker:<8} {d.quantity:>5} {d.conviction:<8} "
                      f"${d.limit_price:>9,.2f} ${d.position_size_usd:>11,.0f} "
                      f"{d.signal_strength:>+6.1f} {d.news_catalyst[:30]}")

        total_sell = sum(d.position_size_usd for d in sells)
        total_buy = sum(d.position_size_usd for d in buys)
        net = total_buy - total_sell
        equity = ctx["equity"]
        cash_after = ctx["cash"] + total_sell - total_buy

        print(f"\n  {'─'*50}")
        print(f"  Total sell value:  ${total_sell:>11,.0f}")
        print(f"  Total buy value:   ${total_buy:>11,.0f}")
        print(f"  Net deployment:    ${net:>+11,.0f}")
        print(f"  Est. cash after:   ${cash_after:>11,.0f} ({cash_after/equity:.0%} of equity)")
        print(f"  {'─'*50}")

        print(f"\n  Execute these {len(sells) + len(buys)} orders? (yes/no): ", end="")
        confirm = input().strip().lower()
        if confirm != "yes":
            print("\n  Execution CANCELLED by user.")
            for d in sells + buys:
                d.execution_notes += " | CANCELLED by user"
            return executed_orders
        print()

    # Execute sells first
    if sells:
        print(f"\n--- Executing {len(sells)} SELL orders ---")
    for d in sells:
        print(f"  SELL {d.quantity} x {d.ticker} @ {d.order_type} ${d.limit_price:,.2f}")
        if live:
            try:
                order_type = "market" if d.order_type == "MARKET" else "limit"
                result = submit_order(
                    symbol=d.ticker,
                    qty=d.quantity,
                    side="sell",
                    order_type=order_type,
                    limit_price=d.limit_price if order_type == "limit" else None,
                    time_in_force="day",
                )
                d.executed = True
                d.execution_notes += f" | Order ID: {result.get('id', 'N/A')}"
                executed_orders.append(result)
                print(f"    -> Order placed: {result.get('id', 'N/A')} status={result.get('status')}")
            except Exception as e:
                d.execution_notes += f" | FAILED: {e}"
                print(f"    -> FAILED: {e}")
        else:
            d.execution_notes += " | DRY RUN — not executed"
            print(f"    -> (dry run)")

    # Refresh cash if sells were executed
    if sells and live:
        print("\n  Waiting for sells to settle...")
        # In practice we'd poll for fill status; for now just re-fetch account
        account = get_account()
        ctx["cash"] = float(account["cash"])
        print(f"  Updated cash: ${ctx['cash']:,.2f}")

    # Execute buys
    if buys:
        print(f"\n--- Executing {len(buys)} BUY orders ---")
    for d in buys:
        print(f"  BUY {d.quantity} x {d.ticker} @ LIMIT ${d.limit_price:,.2f} "
              f"(~${d.position_size_usd:,.0f}, {d.conviction})")
        if live:
            try:
                result = submit_order(
                    symbol=d.ticker,
                    qty=d.quantity,
                    side="buy",
                    order_type="limit",
                    limit_price=d.limit_price,
                    time_in_force="day",
                )
                d.executed = True
                d.execution_notes += f" | Order ID: {result.get('id', 'N/A')}"
                executed_orders.append(result)
                print(f"    -> Order placed: {result.get('id', 'N/A')} status={result.get('status')}")
            except Exception as e:
                d.execution_notes += f" | FAILED: {e}"
                print(f"    -> FAILED: {e}")
        else:
            d.execution_notes += " | DRY RUN — not executed"
            print(f"    -> (dry run)")

    if not sells and not buys:
        print("\n  No orders to execute.")

    return executed_orders


# ---------------------------------------------------------------------------
# Phase 5: Session Closeout (agents.md 8.5)
# ---------------------------------------------------------------------------

def session_closeout(ctx: dict, decisions: list[TradeDecision], live: bool = False, auto: bool = False):
    """Log final state, decisions, and performance metrics."""
    print(f"\n{'=' * 70}")
    print("SESSION CLOSEOUT")
    print("=" * 70)

    # Refresh account if live
    if live:
        account = get_account()
        equity = float(account["equity"])
        cash = float(account["cash"])
    else:
        equity = ctx["equity"]
        cash = ctx["cash"]

    # Decision summary
    buys = [d for d in decisions if d.action == "BUY"]
    sells = [d for d in decisions if d.action == "SELL"]
    holds = [d for d in decisions if d.action == "HOLD"]

    total_buy_value = sum(d.position_size_usd for d in buys)
    total_sell_value = sum(d.position_size_usd for d in sells)

    print(f"\n--- Session Summary ---")
    print(f"  Portfolio equity: ${equity:,.2f}")
    print(f"  Cash:             ${cash:,.2f}")
    print(f"  Cash reserve:     {cash / equity:.1%}")
    print(f"  Decisions:        {len(buys)} buys, {len(sells)} sells, {len(holds)} holds")
    if buys:
        print(f"  Total buy value:  ${total_buy_value:,.2f}")
    if sells:
        print(f"  Total sell value: ${total_sell_value:,.2f}")

    # Log all decisions
    for d in decisions:
        log_trade_decision(d.to_dict())

    # Performance metrics
    metrics = {
        "equity": equity,
        "cash": cash,
        "cash_reserve_pct": round(cash / equity, 4) if equity else 0,
        "num_positions": ctx["num_positions"],
        "buys": len(buys),
        "sells": len(sells),
        "holds": len(holds),
        "total_buy_value": total_buy_value,
        "total_sell_value": total_sell_value,
        "spy": ctx.get("spy", {}),
        "mode": _mode_label(live, auto),
    }
    log_performance(metrics)

    # Log session end
    log_session({
        "phase": "closeout",
        "mode": _mode_label(live, auto),
        "equity": equity,
        "cash": cash,
        "decisions_count": len(decisions),
        "buys": len(buys),
        "sells": len(sells),
    })

    print(f"\n  Logs saved to {LOGS_DIR}/")
    print(f"\n{'=' * 70}")
    print(f"SESSION COMPLETE — {_mode_label(live, auto)}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_session(live: bool = False, auto: bool = False, use_ai: bool = False):
    """Execute a full trading session."""
    # Phase 1: Startup
    ctx = session_startup(live=live, auto=auto, use_ai=use_ai)

    # Phase 2: Analysis
    analysis_results = analysis_phase(ctx, use_ai=use_ai)
    position_decisions = check_existing_positions(ctx)

    # Phase 3: Decisions
    decisions = decision_phase(ctx, analysis_results, position_decisions)

    # Phase 4: Execution
    execution_phase(ctx, decisions, live=live, auto=auto)

    # Phase 5: Closeout
    session_closeout(ctx, decisions, live=live, auto=auto)

    return decisions


def main():
    parser = argparse.ArgumentParser(description="Halal AI Trader — Trading Session")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute real orders (default is dry run)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip confirmation prompt (requires --live)",
    )
    parser.add_argument(
        "--use-ai",
        action="store_true",
        help="Use Claude LLM for news analysis (costs money, better signals)",
    )
    args = parser.parse_args()

    if args.auto and not args.live:
        print("Warning: --auto has no effect without --live. Running in dry-run mode.\n")

    run_session(live=args.live, auto=args.auto and args.live, use_ai=args.use_ai)


if __name__ == "__main__":
    main()

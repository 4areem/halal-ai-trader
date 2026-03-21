# Halal AI Trader

An autonomous AI trading agent that analyzes financial news and market data to make Shariah-compliant investment decisions using the Alpaca paper trading API.

## Overview

Halal AI Trader is a rules-based, AI-assisted swing trading system built for Muslim investors who want to participate in the stock market without compromising their faith. It combines real-time news sentiment analysis with strict adherence to AAOIFI Shariah Standard No. 21 — the international benchmark for Islamic equity screening — to identify, evaluate, and execute trades automatically.

The system operates as a disciplined, emotionless investor. It pulls news from market data APIs, classifies sentiment with source-tier weighting, screens every potential trade against Islamic finance prohibitions and financial ratio thresholds, enforces position sizing and risk limits, detects market regime (bull/sideways/bear) to adjust capital deployment, and logs every decision with full reasoning for audit and review. It never short sells, never uses margin, never trades derivatives, and never invests in prohibited industries.

Built on top of Alpaca's trading API and designed for integration with their official MCP server, the agent runs in either dry-run mode (analysis and decisions without execution) or live mode (real paper trades with a confirmation gate requiring explicit user approval before any order is placed). The entire decision pipeline — from news ingestion to order placement — is transparent, logged, and auditable.

## Features

### Shariah Compliance Screening
- Full implementation of **AAOIFI Standard No. 21** financial screening
- Three-ratio quantitative test: interest-bearing debt / market cap < 30%, interest-bearing securities / market cap < 30%, impure revenue / total revenue < 5%
- Automatic rejection of prohibited industries: alcohol, gambling, conventional banking/insurance, tobacco, weapons, adult entertainment
- Cross-referenced against major Shariah screeners (Musaffa, Zoya, HalalSignalz, Islamicly)
- Dividend purification rate tracking for each holding
- Pre-screened watchlist of 33 compliant large-cap US stocks across 8 sectors

### News Sentiment Analysis
- Real-time news ingestion from Alpaca's market data API (72-hour lookback window)
- **Source tier weighting** per reliability: Tier 1 (SEC filings, earnings) weighted 3x, Tier 2 (Reuters, Bloomberg) 2x, Tier 3 (Benzinga, CNBC) 1.5x, Tier 4 (social media) 1x
- Five-level sentiment classification: Strong Positive through Strong Negative
- Confidence scoring (High/Medium/Low) with article count and signal consistency
- "So What?" framework: Is it priced in? One-time or trend? Does it affect fundamental earning power?
- Weighted aggregate scoring per ticker with signal strength from -2.0 to +2.0

### Risk Management
- **Position sizing**: 10% max per stock, $500 minimum, conviction-based scaling (HIGH = 100%, MEDIUM = 50%)
- **Stop-losses**: 8% hard stop (automatic, no override), 5% trailing stop after 10% gain, 15-day time stop for flat positions
- **Portfolio limits**: 10 positions max, 20% cash reserve minimum, 30% sector concentration cap
- **Drawdown protection**: All new buys halted when portfolio drops 15% from peak
- **Market regime detection**: SPY-based regime classification automatically adjusts capital deployment — 70% in bull markets, 50% in sideways, 30% in bear markets
- **Order discipline**: Limit orders only (no chasing), never buy a stock up 5%+ intraday

### Execution & Safety
- **Dry run mode** (default): Full analysis pipeline with simulated execution — see exactly what would happen
- **Live mode**: Requires explicit `--live` flag, displays complete order confirmation table with all trades, and waits for manual `yes/no` approval before placing any order
- **Sells execute before buys** to free capital and avoid over-deployment
- Orders ranked by conviction (highest first) so capital goes to strongest signals

### Logging & Audit Trail
- Every trade decision logged with structured reasoning (Shariah check, risk check, thesis, catalyst)
- Session snapshots at startup and closeout with portfolio state
- Running performance metrics (equity, cash reserve, positions, deployment vs regime limits)
- Timestamped news analysis archives for post-hoc review of what drove each decision

## Architecture

```
alpaca-ai-trader/
├── agents.md                 # Trading philosophy and rules (the "brain")
├── requirements.txt
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── __main__.py           # Entry point: python -m src.runner
│   ├── config.py             # All parameters from agents.md §12
│   ├── runner.py             # Session orchestrator (startup → analysis → decision → execution → closeout)
│   ├── news_analysis.py      # News fetching, sentiment classification, aggregation
│   ├── shariah_screen.py     # AAOIFI Standard No. 21 screening engine
│   ├── risk_management.py    # Position sizing, stop-losses, drawdown, sector caps
│   ├── trade_executor.py     # Alpaca API wrapper (account, positions, orders, market data)
│   ├── watchlist.py          # Watchlist CRUD and persistence
│   └── logger.py             # Decision, session, and performance logging
│
├── data/
│   ├── watchlist.json        # 33 pre-screened Shariah-compliant stocks
│   ├── review_list.json      # Borderline stocks awaiting further analysis
│   └── rejected.json         # Non-compliant stocks with documented rejection reasons
│
└── logs/                     # Session logs, decisions, news analysis, performance metrics
```

### Session Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        SESSION START                            │
│  Account status · Positions · P&L · Market clock · SPY regime   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NEWS ANALYSIS                              │
│  Fetch articles · Classify sentiment · Tier-weight sources      │
│  Aggregate per ticker · Rank by signal strength                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────┐  ┌──────────────────────────────────────┐
│   EXISTING POSITIONS │  │         BUY CANDIDATES               │
│  Stop-loss checks    │  │  Shariah verified (watchlist)        │
│  Trailing stops      │  │  Risk check (size, cash, sector)    │
│  Time stops          │  │  Regime capital budget               │
│  Thesis review       │  │  Conviction filter                   │
└──────────┬───────────┘  │  Sleep test                          │
           │              └──────────────┬───────────────────────┘
           │                             │
           └────────────┬────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     DECISION PHASE                              │
│  Generate structured TRADE DECISION LOG for every action        │
│  Apply regime-based deployment limits                           │
│  Rank buys by conviction · Downsize to fit budget               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      EXECUTION                                  │
│  [LIVE] Show confirmation table → require yes/no                │
│  Sell orders first · Refresh cash · Buy orders by conviction    │
│  Limit orders · Log confirmations                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SESSION CLOSEOUT                            │
│  Final portfolio snapshot · Decision log · Performance metrics  │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

A single trading session follows five phases:

**1. Startup** — The agent connects to Alpaca, fetches account equity and cash balances, loads all open positions with unrealized P&L, checks the market clock, and pulls SPY data to determine the current market regime (bull, sideways, or bear). This regime sets the capital deployment ceiling for the session.

**2. Analysis** — The news pipeline fetches articles for all 33 watchlist tickers from the last 72 hours. Each article is classified by sentiment and confidence, with source reliability weighting (an FDA approval from a press release carries more weight than a speculative blog post). Sentiment is aggregated per ticker into a signal strength score from -2.0 to +2.0. Existing positions are checked against stop-loss thresholds.

**3. Decision** — Actionable signals (|strength| >= 0.5) are processed through the full decision framework. Buy candidates pass through: Shariah verification (already pre-screened but confirmed), risk checks (position size, cash reserve, sector cap, drawdown status), regime budget enforcement, conviction sizing (HIGH = full 10% position, MEDIUM = 5% half-size), and the sleep test ("would I be comfortable holding this for two weeks without checking?"). Every decision — buy, sell, hold, or no action — generates a structured log with complete reasoning.

**4. Execution** — In live mode, a confirmation table shows every proposed order with ticker, quantity, price, value, conviction, and signal strength, plus net deployment and estimated cash balance. The user must type `yes` to proceed. Sells execute before buys to free capital. All orders use limit prices set slightly below the current ask.

**5. Closeout** — The session logs final portfolio state, all decisions with reasoning, and performance metrics to timestamped JSON files for historical analysis.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Trading API | [Alpaca Markets](https://alpaca.markets/) (paper trading) |
| MCP Integration | [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server) |
| Market Data | Alpaca Data API v2 (news, quotes, bars, snapshots) |
| Shariah Screening | Custom implementation of AAOIFI Standard No. 21 |
| Screener Validation | Musaffa, Zoya, HalalSignalz, Islamicly, Muslim Xchange |
| Configuration | python-dotenv for environment management |
| Data Format | JSON (watchlists, logs, decisions, performance) |

## Setup

### Prerequisites
- Python 3.12+
- An [Alpaca](https://alpaca.markets/) account (free paper trading account works)
- [uv](https://docs.astral.sh/uv/) (for the MCP server, optional)

### Installation

```bash
git clone https://github.com/your-username/alpaca-ai-trader.git
cd alpaca-ai-trader
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

Get your API keys from the [Alpaca Dashboard](https://app.alpaca.markets/) under API Keys. Use paper trading keys, not live keys.

### Optional: Alpaca MCP Server

To enable Claude Code integration with Alpaca:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Configure `.claude/settings.local.json`:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "your_api_key_here",
        "ALPACA_SECRET_KEY": "your_secret_key_here",
        "ALPACA_PAPER_TRADE": "True"
      }
    }
  }
}
```

### Running

```bash
# Dry run — full analysis, no real orders
python -m src.runner

# Live mode — real paper trades (with confirmation prompt)
python -m src.runner --live
```

### Verify Connection

```bash
python -c "from src.trade_executor import get_account; a = get_account(); print(f'Connected: {a[\"status\"]} — Equity: \${a[\"equity\"]}')"
```

## Performance

This system is currently in the **paper trading validation phase** with a 90-day evaluation period, starting with a $100,000 simulated portfolio.

### Tracked Metrics
- **Win rate** — Percentage of trades closed at a profit
- **Average win vs average loss** — Are winners bigger than losers?
- **Maximum drawdown** — Largest peak-to-trough decline
- **Cash utilization** — Percentage of capital actively deployed
- **Sector concentration** — Diversification across industries
- **Regime compliance** — Did the system respect bull/sideways/bear capital limits?
- **Shariah compliance** — Zero tolerance: every trade must pass screening

### Evaluation Criteria (from agents.md)
- **30 days**: Is the process working? Are decisions logical?
- **60 days**: Compare against SPY. Are drawdowns smaller?
- **90 days**: If within 2% of SPY with lower drawdowns and full Shariah compliance, the strategy is validated for consideration with real capital

### Results

*Paper trading in progress. Results will be published here as the 90-day period unfolds.*

## Disclaimer

This software is provided for **educational and research purposes only**. It is not financial advice and should not be used as the sole basis for any investment decision.

**Trading risk**: All trading involves risk of loss. Paper trading results do not guarantee future performance with real capital. Past performance is not indicative of future results.

**Shariah compliance**: This project implements Islamic finance screening based on AAOIFI Standard No. 21 and cross-references multiple established Shariah screeners. However, it is a software implementation, not a fatwa. The default ruling of permissibility (al-asl fil-ashya al-ibahah) guides borderline cases, but **users should consult qualified Islamic scholars** for personal Shariah compliance guidance on their investments. Screening criteria can vary between scholars and standards bodies.

**Not affiliated**: This project is not affiliated with, endorsed by, or sponsored by Alpaca Markets, AAOIFI, or any of the Shariah screening services referenced (Musaffa, Zoya, HalalSignalz, Islamicly, Muslim Xchange).

---

*Bismillah. Trade with knowledge, discipline, and tawakkul.*

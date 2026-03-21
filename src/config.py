"""Configuration loaded from environment and agents.md parameters."""

import os
from dotenv import load_dotenv

load_dotenv()

# Alpaca API
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# Anthropic API (for LLM-powered news analysis)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AI_MODEL = "claude-sonnet-4-20250514"

# Trading Parameters
MAX_POSITION_PCT = 0.10
MAX_POSITIONS = 10
MIN_POSITION_USD = 500
CASH_RESERVE_PCT = 0.20
STOP_LOSS_PCT = 0.08
TRAILING_STOP_ACTIVATION = 0.10
TRAILING_STOP_PCT = 0.05
TIME_STOP_DAYS = 15
MAX_SECTOR_PCT = 0.30
DRAWDOWN_HALT_PCT = 0.15
MIN_HOLD_DAYS = 2

# Shariah Thresholds (AAOIFI Standard No. 21)
MAX_DEBT_RATIO = 0.30
MAX_SECURITIES_RATIO = 0.30
MAX_IMPURE_REVENUE = 0.05

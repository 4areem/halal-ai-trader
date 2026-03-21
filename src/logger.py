"""Logging for trade decisions, session activity, and performance tracking."""

import json
import os
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


def _ensure_logs_dir():
    os.makedirs(LOGS_DIR, exist_ok=True)


def log_trade_decision(decision: dict) -> None:
    """Append a trade decision to the daily log file."""
    _ensure_logs_dir()
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(LOGS_DIR, f"decisions_{date_str}.json")

    entries = []
    if os.path.exists(path):
        with open(path) as f:
            entries = json.load(f)

    decision["timestamp"] = datetime.now().isoformat()
    entries.append(decision)

    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def log_session(session_data: dict) -> None:
    """Log session start/end with portfolio snapshot."""
    _ensure_logs_dir()
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(LOGS_DIR, f"session_{date_str}.json")

    session_data["timestamp"] = datetime.now().isoformat()
    with open(path, "w") as f:
        json.dump(session_data, f, indent=2)


def log_performance(metrics: dict) -> None:
    """Append performance metrics to the running log."""
    _ensure_logs_dir()
    path = os.path.join(LOGS_DIR, "performance.json")

    entries = []
    if os.path.exists(path):
        with open(path) as f:
            entries = json.load(f)

    metrics["timestamp"] = datetime.now().isoformat()
    entries.append(metrics)

    with open(path, "w") as f:
        json.dump(entries, f, indent=2)

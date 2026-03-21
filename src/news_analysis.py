"""News analysis pipeline per agents.md Section 4.

Pulls news from Alpaca API, structures it for AI analysis, and logs results.
The actual sentiment classification is done by the AI agent at runtime —
this module provides the data fetching, structures, and persistence layer.
"""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum

import requests

from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY

ALPACA_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")


# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------

class Sentiment(Enum):
    STRONG_POSITIVE = "strong_positive"
    MILD_POSITIVE = "mild_positive"
    NEUTRAL = "neutral"
    MILD_NEGATIVE = "mild_negative"
    STRONG_NEGATIVE = "strong_negative"


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceTier(Enum):
    TIER_1 = 1  # SEC filings, earnings, Fed statements, press releases
    TIER_2 = 2  # Reuters, Bloomberg, WSJ, FT, AP
    TIER_3 = 3  # CNBC, MarketWatch, Seeking Alpha, Barron's, Benzinga
    TIER_4 = 4  # Social media, Reddit, blogs
    IGNORE = 5  # Clickbait, pump-and-dump


SOURCE_TIER_MAP = {
    # Tier 1
    "sec": SourceTier.TIER_1,
    "press_release": SourceTier.TIER_1,
    "earnings": SourceTier.TIER_1,
    "fed": SourceTier.TIER_1,
    "business_wire": SourceTier.TIER_1,
    "pr_newswire": SourceTier.TIER_1,
    "globenewswire": SourceTier.TIER_1,
    # Tier 2
    "reuters": SourceTier.TIER_2,
    "bloomberg": SourceTier.TIER_2,
    "wsj": SourceTier.TIER_2,
    "wall_street_journal": SourceTier.TIER_2,
    "ft": SourceTier.TIER_2,
    "financial_times": SourceTier.TIER_2,
    "ap": SourceTier.TIER_2,
    "associated_press": SourceTier.TIER_2,
    # Tier 3
    "cnbc": SourceTier.TIER_3,
    "marketwatch": SourceTier.TIER_3,
    "seeking_alpha": SourceTier.TIER_3,
    "barrons": SourceTier.TIER_3,
    "benzinga": SourceTier.TIER_3,
    "yahoo_finance": SourceTier.TIER_3,
    "investors_business_daily": SourceTier.TIER_3,
    "the_motley_fool": SourceTier.TIER_3,
    "zacks": SourceTier.TIER_3,
    # Tier 4
    "reddit": SourceTier.TIER_4,
    "twitter": SourceTier.TIER_4,
    "stocktwits": SourceTier.TIER_4,
}

# Sentiment numeric scores for aggregation
SENTIMENT_SCORES = {
    Sentiment.STRONG_POSITIVE: 2,
    Sentiment.MILD_POSITIVE: 1,
    Sentiment.NEUTRAL: 0,
    Sentiment.MILD_NEGATIVE: -1,
    Sentiment.STRONG_NEGATIVE: -2,
}


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class NewsItem:
    headline: str
    source: str
    ticker: str
    url: str = ""
    created_at: str = ""
    summary: str = ""
    symbols: list[str] = field(default_factory=list)
    # Fields populated by AI analysis
    sentiment: Sentiment = Sentiment.NEUTRAL
    confidence: Confidence = Confidence.LOW
    source_tier: SourceTier = SourceTier.TIER_3
    already_priced_in: bool = False
    is_trend: bool = False
    affects_fundamentals: bool = False
    so_what_reasoning: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sentiment"] = self.sentiment.value
        d["confidence"] = self.confidence.value
        d["source_tier"] = self.source_tier.value
        return d


@dataclass
class TickerAnalysis:
    ticker: str
    company_name: str
    items: list[NewsItem]
    overall_sentiment: Sentiment = Sentiment.NEUTRAL
    overall_confidence: Confidence = Confidence.LOW
    actionable: bool = False
    signal_strength: float = 0.0  # -2.0 to +2.0
    reasoning: str = ""
    recommended_action: str = "NO ACTION"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "news_count": len(self.items),
            "overall_sentiment": self.overall_sentiment.value,
            "overall_confidence": self.overall_confidence.value,
            "actionable": self.actionable,
            "signal_strength": self.signal_strength,
            "reasoning": self.reasoning,
            "recommended_action": self.recommended_action,
            "items": [item.to_dict() for item in self.items],
        }


# ---------------------------------------------------------------------------
# Source Classification
# ---------------------------------------------------------------------------

def classify_source(source_name: str) -> SourceTier:
    """Map a source name to its reliability tier."""
    key = source_name.lower().strip().replace(" ", "_").replace("-", "_")
    return SOURCE_TIER_MAP.get(key, SourceTier.TIER_4)


# ---------------------------------------------------------------------------
# News Fetching
# ---------------------------------------------------------------------------

def _alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }


def fetch_news_alpaca(
    symbols: list[str],
    hours_back: int = 72,
    limit_per_request: int = 50,
) -> list[dict]:
    """Fetch news from Alpaca API for given symbols.

    Alpaca limits to 50 articles per request, so we batch symbols
    to maximize coverage across the watchlist.
    """
    all_articles = []
    seen_ids = set()

    start = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()

    # Alpaca accepts comma-separated symbols, but too many can dilute results.
    # Batch in groups of 10.
    for i in range(0, len(symbols), 10):
        batch = symbols[i : i + 10]
        params = {
            "symbols": ",".join(batch),
            "limit": limit_per_request,
            "sort": "desc",
            "start": start,
        }

        try:
            resp = requests.get(
                ALPACA_NEWS_URL,
                headers=_alpaca_headers(),
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            for article in data.get("news", []):
                aid = article.get("id")
                if aid not in seen_ids:
                    seen_ids.add(aid)
                    all_articles.append(article)
        except requests.RequestException as e:
            print(f"  Warning: Alpaca news fetch failed for {batch}: {e}")

    return all_articles


def parse_alpaca_article(article: dict, target_ticker: str) -> NewsItem:
    """Convert a raw Alpaca news article dict into a NewsItem."""
    source = article.get("source", "unknown")
    return NewsItem(
        headline=_clean_html(article.get("headline", "")),
        source=source,
        ticker=target_ticker,
        url=article.get("url", ""),
        created_at=article.get("created_at", ""),
        summary=_clean_html(article.get("summary", "")),
        symbols=article.get("symbols", []),
        source_tier=classify_source(source),
    )


def _clean_html(text: str) -> str:
    """Strip HTML entities and tags from text."""
    text = text.replace("&#39;", "'").replace("&amp;", "&")
    text = text.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# News Pipeline
# ---------------------------------------------------------------------------

def fetch_watchlist_news(
    watchlist: list[dict],
    hours_back: int = 72,
) -> dict[str, list[NewsItem]]:
    """Fetch news for all tickers in the watchlist.

    Returns a dict mapping ticker -> list of NewsItem.
    """
    symbols = [s["ticker"] for s in watchlist]
    print(f"Fetching news for {len(symbols)} tickers (last {hours_back}h)...")

    raw_articles = fetch_news_alpaca(symbols, hours_back=hours_back)
    print(f"  Retrieved {len(raw_articles)} total articles from Alpaca")

    # Map articles to tickers. An article can mention multiple symbols.
    ticker_news: dict[str, list[NewsItem]] = {s: [] for s in symbols}
    watchlist_set = set(symbols)

    for article in raw_articles:
        article_symbols = article.get("symbols", [])
        for sym in article_symbols:
            if sym in watchlist_set:
                item = parse_alpaca_article(article, sym)
                ticker_news[sym].append(item)

    # Stats
    tickers_with_news = sum(1 for v in ticker_news.values() if v)
    total_items = sum(len(v) for v in ticker_news.values())
    print(f"  {tickers_with_news}/{len(symbols)} tickers have news")
    print(f"  {total_items} total news items mapped to watchlist tickers")

    return ticker_news


def build_analysis_prompt(
    ticker: str,
    company_name: str,
    items: list[NewsItem],
) -> str:
    """Build a structured prompt for AI sentiment analysis of a ticker's news.

    This is called by the agent to get the prompt it should analyze.
    """
    headlines_block = ""
    for i, item in enumerate(items, 1):
        tier_label = f"Tier {item.source_tier.value}" if item.source_tier != SourceTier.IGNORE else "IGNORE"
        headlines_block += f"""
Article {i}:
  Headline: {item.headline}
  Source: {item.source} ({tier_label})
  Date: {item.created_at}
  Summary: {item.summary or '(none)'}
  Other tickers mentioned: {', '.join(item.symbols) if item.symbols else 'none'}
"""

    return f"""Analyze the following {len(items)} news articles for {ticker} ({company_name}).

For EACH article, determine:
1. Sentiment: STRONG_POSITIVE / MILD_POSITIVE / NEUTRAL / MILD_NEGATIVE / STRONG_NEGATIVE
2. Confidence: HIGH / MEDIUM / LOW
3. "So What?" test:
   - Is this already priced in? (widely known for hours with no stock movement = yes)
   - One-time event or part of a trend?
   - Does it affect fundamental earning power?

Then provide an OVERALL assessment:
- Overall sentiment for {ticker}
- Whether this is ACTIONABLE (should we consider buying, selling, or is it noise?)
- Signal strength: -2.0 (strong sell signal) to +2.0 (strong buy signal)
- Recommended action: BUY_SIGNAL / SELL_SIGNAL / HOLD / NO_ACTION

Weight Tier 1-2 sources more heavily than Tier 3-4.
{headlines_block}

Respond in this exact JSON format:
{{
  "articles": [
    {{
      "article_num": 1,
      "sentiment": "STRONG_POSITIVE",
      "confidence": "HIGH",
      "already_priced_in": false,
      "is_trend": true,
      "affects_fundamentals": true,
      "reasoning": "brief explanation"
    }}
  ],
  "overall": {{
    "sentiment": "MILD_POSITIVE",
    "confidence": "MEDIUM",
    "actionable": true,
    "signal_strength": 0.8,
    "reasoning": "2-3 sentence summary of the overall picture",
    "recommended_action": "NO_ACTION"
  }}
}}"""


def aggregate_sentiment(items: list[NewsItem]) -> tuple[Sentiment, float]:
    """Compute weighted average sentiment from analyzed news items.

    Returns (overall_sentiment, signal_strength).
    Weights: Tier 1 = 3x, Tier 2 = 2x, Tier 3 = 1.5x, Tier 4 = 1x.
    HIGH confidence = 2x, MEDIUM = 1x, LOW = 0.5x.
    """
    if not items:
        return Sentiment.NEUTRAL, 0.0

    tier_weights = {
        SourceTier.TIER_1: 3.0,
        SourceTier.TIER_2: 2.0,
        SourceTier.TIER_3: 1.5,
        SourceTier.TIER_4: 1.0,
        SourceTier.IGNORE: 0.0,
    }
    conf_weights = {
        Confidence.HIGH: 2.0,
        Confidence.MEDIUM: 1.0,
        Confidence.LOW: 0.5,
    }

    weighted_sum = 0.0
    total_weight = 0.0

    for item in items:
        score = SENTIMENT_SCORES[item.sentiment]
        w = tier_weights.get(item.source_tier, 1.0) * conf_weights.get(item.confidence, 1.0)
        weighted_sum += score * w
        total_weight += w

    if total_weight == 0:
        return Sentiment.NEUTRAL, 0.0

    avg = weighted_sum / total_weight

    # Map average score back to sentiment
    if avg >= 1.5:
        sentiment = Sentiment.STRONG_POSITIVE
    elif avg >= 0.5:
        sentiment = Sentiment.MILD_POSITIVE
    elif avg > -0.5:
        sentiment = Sentiment.NEUTRAL
    elif avg > -1.5:
        sentiment = Sentiment.MILD_NEGATIVE
    else:
        sentiment = Sentiment.STRONG_NEGATIVE

    return sentiment, round(avg, 2)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def save_analysis_results(
    results: list[TickerAnalysis],
    run_timestamp: str | None = None,
) -> str:
    """Save analysis results to logs/ directory. Returns the file path."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts = run_timestamp or datetime.now().strftime("%Y-%m-%d_%H%M")
    path = os.path.join(LOGS_DIR, f"news_analysis_{ts}.json")

    output = {
        "run_timestamp": ts,
        "total_tickers_analyzed": len(results),
        "actionable_count": sum(1 for r in results if r.actionable),
        "results": [r.to_dict() for r in results],
    }

    with open(path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Analysis saved to {path}")
    return path


def print_signal_report(results: list[TickerAnalysis]) -> None:
    """Print a ranked summary of actionable signals."""
    # Sort by absolute signal strength descending
    ranked = sorted(results, key=lambda r: abs(r.signal_strength), reverse=True)

    print("\n" + "=" * 70)
    print("NEWS SIGNAL REPORT")
    print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    actionable = [r for r in ranked if r.actionable]
    non_actionable = [r for r in ranked if not r.actionable]

    if actionable:
        print(f"\n--- ACTIONABLE SIGNALS ({len(actionable)}) ---")
        for r in actionable:
            direction = "+" if r.signal_strength > 0 else ""
            print(
                f"  {r.ticker:6s} | {direction}{r.signal_strength:+.1f} | "
                f"{r.overall_sentiment.value:18s} | {r.overall_confidence.value:6s} | "
                f"{r.recommended_action:12s} | {len(r.items)} articles"
            )
            if r.reasoning:
                # Truncate long reasoning for the summary view
                short = r.reasoning[:120] + "..." if len(r.reasoning) > 120 else r.reasoning
                print(f"         {short}")
    else:
        print("\n  No actionable signals found.")

    if non_actionable:
        tickers_with_news = [r for r in non_actionable if r.items]
        tickers_no_news = [r for r in non_actionable if not r.items]
        if tickers_with_news:
            print(f"\n--- NEUTRAL / LOW CONFIDENCE ({len(tickers_with_news)}) ---")
            for r in tickers_with_news:
                print(f"  {r.ticker:6s} | {r.signal_strength:+.1f} | {len(r.items)} articles | {r.reasoning[:80]}")

        if tickers_no_news:
            no_news_tickers = [r.ticker for r in tickers_no_news]
            print(f"\n--- NO NEWS ({len(no_news_tickers)}) ---")
            # Print in rows of 10
            for i in range(0, len(no_news_tickers), 10):
                print(f"  {', '.join(no_news_tickers[i:i+10])}")

    print("=" * 70)

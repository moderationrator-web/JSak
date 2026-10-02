"""Assign each market to a coarse category.

Uses Gamma event tags when they were fetched (``--enrich-tags``), otherwise a
keyword classifier over the event slug, market slug and title.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from .api import ApiError, Client

CATEGORIES = ["Politics", "Sports", "Esports", "Crypto", "Economics", "Tech", "Culture",
              "Mentions", "Weather", "Other"]

# Checked in order; first hit wins. Tokens match whole slug/title words,
# phrases match as substrings of the normalised text.
_RULES = [
    ("Weather", {"temperature", "weather", "hurricane", "rainfall", "snowfall", "celsius",
                 "fahrenheit", "tornado", "heatwave"}, ["highest temperature", "lowest temperature"]),
    ("Mentions", {"mention", "mentions", "tweets", "tweet"},
     ["say ", "said ", "how many times", "# of tweets", "number of tweets", "post on x"]),
    ("Esports", {"esports", "lol", "lck", "lec", "lpl", "dota", "dota2", "valorant", "cs2", "csgo",
                 "counterstrike", "overwatch", "rocket-league", "msi", "worlds"},
     ["league of legends", "counter-strike", "counter strike", "rainbow six"]),
    ("Sports", {"nba", "nfl", "mlb", "nhl", "wnba", "mls", "epl", "ucl", "uel", "ufc", "mma", "boxing",
                "tennis", "atp", "wta", "golf", "pga", "liv", "f1", "nascar", "ncaa", "ncaab", "ncaaf",
                "cfb", "cbb", "fifa", "uefa", "cricket", "ipl", "laliga", "bundesliga", "seriea",
                "ligue1", "rugby", "olympics", "superbowl", "playoffs", "stanley", "wimbledon",
                "touchdown", "quarterback", "mvp", "goalscorer", "championship", "match", "game",
                "vs", "spread", "o/u", "moneyline", "kbo", "npb", "afl", "euroleague", "copa"},
     ["premier league", "champions league", "la liga", "serie a", "ligue 1", "world cup",
      "super bowl", "grand prix", "formula 1", "world series", "stanley cup", "nba finals",
      "us open", "french open", "australian open", " vs. ", " vs ", "both teams to score"]),
    ("Crypto", {"bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "doge", "dogecoin",
                "crypto", "memecoin", "token", "airdrop", "fdv", "stablecoin", "usdt", "usdc", "bnb",
                "hyperliquid", "pump", "coinbase", "binance", "altcoin", "satoshi", "microstrategy"},
     ["up or down", "up-or-down", "market cap", "all time high", "all-time high"]),
    ("Economics", {"fed", "fomc", "cpi", "inflation", "gdp", "recession", "unemployment", "payrolls",
                   "nfp", "tariff", "tariffs", "treasury", "yield", "yields", "bps", "powell", "ecb",
                   "boe", "boj", "spx", "nasdaq", "dow", "stock", "stocks", "earnings", "ipo", "oil",
                   "gold", "silver", "s&p", "equities", "shares", "revenue", "debt", "shutdown"},
     ["interest rate", "rate cut", "rate hike", "jobs report", "s&p 500", "close above", "close below"]),
    ("Tech", {"ai", "openai", "chatgpt", "gpt", "gemini", "anthropic", "claude", "llm", "apple",
              "iphone", "google", "microsoft", "nvidia", "tesla", "spacex", "starship", "launch",
              "meta", "grok", "xai", "deepseek", "robotaxi", "neuralink", "tiktok"}, ["app store"]),
    ("Culture", {"oscars", "oscar", "grammy", "grammys", "emmy", "emmys", "movie", "film", "album",
                 "song", "spotify", "billboard", "netflix", "celebrity", "pope", "eurovision",
                 "youtube", "mrbeast", "kardashian", "bachelor", "survivor"},
     ["box office", "rotten tomatoes", "golden globe", "person of the year", "taylor swift"]),
    ("Politics", {"election", "elections", "president", "presidential", "trump", "biden", "harris",
                  "vance", "senate", "house", "congress", "governor", "mayor", "primary", "democrat",
                  "democrats", "republican", "republicans", "gop", "dnc", "rnc", "parliament",
                  "minister", "chancellor", "nominee", "nomination", "cabinet", "impeach",
                  "impeachment", "putin", "zelensky", "ukraine", "russia", "israel", "iran", "gaza",
                  "hamas", "ceasefire", "nato", "china", "taiwan", "supreme", "scotus", "vote",
                  "referendum", "poll", "polls", "approval", "sanctions", "war", "invade", "coup",
                  "electoral", "seats", "party", "pardon", "resign", "deport", "doge", "musk"},
     ["prime minister", "white house", "executive order", "popular vote"]),
]

# Gamma tag label -> category, checked in order.
_TAG_MAP = [
    ("Weather", ["weather", "climate", "temperature"]),
    ("Mentions", ["mention", "mentions", "tweet markets"]),
    ("Esports", ["esports", "league of legends", "counter-strike", "dota", "valorant", "cs2"]),
    ("Sports", ["sports", "nba", "nfl", "mlb", "nhl", "soccer", "football", "tennis", "golf", "ufc",
                "f1", "formula 1", "cricket", "boxing", "basketball", "baseball", "hockey", "games"]),
    ("Crypto", ["crypto", "bitcoin", "ethereum", "solana", "xrp", "crypto prices"]),
    ("Economics", ["economy", "economics", "fed", "fed rates", "finance", "business", "stocks",
                   "inflation", "earnings", "macro", "commodities"]),
    ("Tech", ["tech", "ai", "science", "big tech", "space"]),
    ("Culture", ["pop culture", "culture", "movies", "music", "celebrities", "awards", "entertainment"]),
    ("Politics", ["politics", "elections", "geopolitics", "us election", "world", "global elections",
                  "trump", "middle east", "ukraine"]),
]

_WORD = re.compile(r"[a-z0-9&/]+")


def _normalise(*parts: Optional[str]) -> str:
    text = " ".join(p for p in parts if p)
    return " " + text.lower().replace("-", " ").replace("_", " ") + " "


def classify_text(title: str = "", slug: str = "", event_slug: str = "") -> str:
    text = _normalise(event_slug, slug, title)
    words = set(_WORD.findall(text))
    for category, tokens, phrases in _RULES:
        if words & tokens or any(p in text for p in phrases):
            return category
    return "Other"


def classify_tags(labels: Iterable[str]) -> Optional[str]:
    low = {str(l).strip().lower() for l in labels if l}
    for category, keys in _TAG_MAP:
        if low & set(keys):
            return category
    return None


class Categorizer:
    def __init__(self, event_tags: Optional[Dict[str, List[str]]] = None):
        self.event_tags = event_tags or {}
        self._cache: Dict[str, str] = {}

    def __call__(self, market: dict) -> str:
        key = market.get("eventSlug") or market.get("slug") or market.get("title") or ""
        if key in self._cache:
            return self._cache[key]
        cat = None
        tags = self.event_tags.get(market.get("eventSlug") or "")
        if tags:
            cat = classify_tags(tags)
        if not cat:
            cat = classify_text(market.get("title", ""), market.get("slug", ""), market.get("eventSlug", ""))
        self._cache[key] = cat
        return cat


def fetch_event_tags(client: Client, event_slugs: Iterable[str], known: Optional[Dict[str, List[str]]] = None,
                     log=None) -> Dict[str, List[str]]:
    """Look up Gamma tags for event slugs (one request per slug, results cached by caller)."""
    tags: Dict[str, List[str]] = dict(known or {})
    for slug in event_slugs:
        if not slug or slug in tags:
            continue
        try:
            res = client.gamma("/events", slug=slug)
        except ApiError as e:
            if log:
                log(f"  gamma tags for {slug} failed: {e}")
            tags[slug] = []
            continue
        events = res if isinstance(res, list) else [res] if isinstance(res, dict) else []
        labels: List[str] = []
        for ev in events:
            for t in ev.get("tags") or []:
                if isinstance(t, dict) and t.get("label"):
                    labels.append(t["label"])
        tags[slug] = labels
    return tags

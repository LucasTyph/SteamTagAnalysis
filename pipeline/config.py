"""Central configuration. Values here are defaults; CLI flags override per run."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "steam.sqlite"

load_dotenv(ROOT / ".env")


def steam_api_key() -> str | None:
    key = os.environ.get("STEAM_API_KEY", "").strip()
    return key or None


@dataclass(frozen=True)
class HostLimit:
    """Minimum seconds between requests to one host, plus random jitter."""

    min_interval: float
    jitter: float = 0.25


@dataclass(frozen=True)
class FetchConfig:
    # api.steampowered.com allows ~100k calls/day per key; store.steampowered.com
    # is stricter (~200 per 5 min is the commonly observed ceiling).
    host_limits: dict[str, HostLimit] = field(
        default_factory=lambda: {
            "api.steampowered.com": HostLimit(min_interval=1.0),
            "store.steampowered.com": HostLimit(min_interval=1.6),
        }
    )
    default_limit: HostLimit = HostLimit(min_interval=1.5)
    timeout: float = 30.0
    max_retries: int = 5
    backoff_base: float = 2.0
    backoff_max: float = 120.0
    # A job moves to "failed" after this many failed attempts.
    max_job_attempts: int = 3
    # Apps per GetItems request. Measured 2026-11-18: 200 works, 400 → HTTP 400.
    items_batch_size: int = 200
    user_agent: str = "steam-tag-analysis/0.1 (non-commercial research project)"


FETCH = FetchConfig()

ANALYSIS_DB_PATH = DATA_DIR / "analysis.duckdb"


@dataclass(frozen=True)
class BuildConfig:
    # Games with fewer reviews stay in `games` but are left out of tag-mix analysis.
    min_reviews: int = 20
    # A tag counts for a game if it is in the game's top N tags by votes…
    tag_max_rank: int = 10
    # …or (optional) has at least this share of the top tag's votes. Off by default:
    # vote shares decline slowly, so a share cutoff readmits almost every tag
    # (see notebooks/01_explore_tags.ipynb).
    tag_min_share: float | None = None


BUILD = BuildConfig()

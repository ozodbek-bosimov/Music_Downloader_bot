"""Lightweight in-memory download metrics.

Tracks which source actually delivered each download since the process
started, so the admin `/stats` command can reveal when YouTube is failing and
the bot is silently degrading to the SoundCloud fallback. Counts reset on
restart — this is a live health signal, not long-term analytics.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock

# Recognised sources, so /stats can render a stable, ordered summary.
YOUTUBE = 'youtube'
SOUNDCLOUD = 'soundcloud'
NONE = 'none'

_lock = Lock()
_counts: Counter[str] = Counter()


def record(source: str) -> None:
    """Record one completed download attempt by its delivering source."""
    with _lock:
        _counts[source] += 1


def snapshot() -> dict[str, int]:
    """Return a copy of the current counts."""
    with _lock:
        return dict(_counts)

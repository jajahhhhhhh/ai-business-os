"""Reciprocal Rank Fusion over id-rankings (pure, deterministic).

Standard RRF (Cormack et al.): each ranking contributes 1 / (k + rank) for
every id it contains, 1-based rank, k = 60 by default. Used to merge the
Meilisearch (keyword) and Qdrant (semantic) result lists — M2 ships RRF only;
a cross-encoder reranker is registered as tech debt (docs/tech-debt.md).
"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_K = 60


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = DEFAULT_K) -> list[tuple[str, float]]:
    """Fuse rankings of ids into a single (id, score) list.

    Ordering is stable: score descending, then id ascending on ties.
    Duplicate ids within one ranking are counted once, at their best rank.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        rank = 0
        for item in ranking:
            if item in seen:
                continue
            seen.add(item)
            rank += 1
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))

"""Reciprocal Rank Fusion: scores, ties, duplicates, edge cases."""

from __future__ import annotations

import pytest

from src.domain.fusion import rrf_fuse


def test_standard_two_ranking_fusion() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    scores = dict(fused)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 63)
    assert scores["d"] == pytest.approx(1 / 63)


def test_tie_stability_orders_by_id() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    # a ties with b, c ties with d -> id ascending within each tie.
    assert [item for item, _ in fused] == ["a", "b", "c", "d"]


def test_disjoint_lists_keep_rank_order() -> None:
    fused = rrf_fuse([["x", "z"], ["y", "w"]])
    scores = dict(fused)
    assert scores["x"] == scores["y"] == pytest.approx(1 / 61)
    assert scores["z"] == scores["w"] == pytest.approx(1 / 62)
    assert [item for item, _ in fused] == ["x", "y", "w", "z"]


def test_identical_lists_double_scores() -> None:
    single = dict(rrf_fuse([["p", "q"]]))
    double = dict(rrf_fuse([["p", "q"], ["p", "q"]]))
    assert double["p"] == pytest.approx(2 * single["p"])
    assert double["q"] == pytest.approx(2 * single["q"])


def test_duplicates_within_one_ranking_counted_once() -> None:
    scores = dict(rrf_fuse([["a", "a", "b"]]))
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62)


def test_empty_inputs() -> None:
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_custom_k() -> None:
    scores = dict(rrf_fuse([["a"]], k=1))
    assert scores["a"] == pytest.approx(1 / 2)


def test_non_positive_k_rejected() -> None:
    with pytest.raises(ValueError):
        rrf_fuse([["a"]], k=0)

"""Line-based text diffing for competitor snapshots (M3). Pure stdlib."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

# Cap on the unified-diff excerpt handed to the ChangeAnalyst LLM (spec §M3).
EXCERPT_MAX_CHARS = 8000


@dataclass(frozen=True, slots=True)
class TextDiff:
    """What changed between two normalized snapshots.

    added/removed are whole lines (tuples for immutability); excerpt is a
    unified-diff-style rendering capped at EXCERPT_MAX_CHARS; change_ratio is
    0.0 (identical) .. 1.0 (nothing in common).
    """

    added: tuple[str, ...]
    removed: tuple[str, ...]
    excerpt: str
    change_ratio: float


def diff_texts(old: str, new: str) -> TextDiff:
    old_lines = old.splitlines()
    new_lines = new.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    change_ratio = round(1.0 - matcher.ratio(), 4) if (old_lines or new_lines) else 0.0

    added: list[str] = []
    removed: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op in ("replace", "delete"):
            removed.extend(old_lines[i1:i2])
        if op in ("replace", "insert"):
            added.extend(new_lines[j1:j2])

    if change_ratio == 0.0 and not added and not removed:
        return TextDiff(added=(), removed=(), excerpt="", change_ratio=0.0)

    excerpt = "\n".join(
        difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after", lineterm="")
    )
    if len(excerpt) > EXCERPT_MAX_CHARS:
        excerpt = excerpt[: EXCERPT_MAX_CHARS - 1] + "…"

    return TextDiff(
        added=tuple(added),
        removed=tuple(removed),
        excerpt=excerpt,
        change_ratio=change_ratio,
    )

"""Matching rules: outgoing bank transactions vs pending contractor draws.

Pure functions over minimal projections; the application layer supplies the
pending-draw list and persists whatever proposal comes back.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PendingDraw:
    """The minimal projection of a pending draw the matcher needs."""

    id: uuid.UUID
    amount_thb: Decimal
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class MatchProposal:
    """A proposed draw for an outgoing transaction.

    ambiguous is True when several pending draws share the amount; the oldest
    one (by requested_at) is proposed but the owner must confirm.
    """

    draw_id: uuid.UUID
    ambiguous: bool


def propose_match(
    direction: str, amount_thb: Decimal, pending_draws: Sequence[PendingDraw]
) -> MatchProposal | None:
    """Propose the pending draw an outgoing transaction most likely pays.

    Only 'out' transactions match draws. Exactly one equal-amount candidate is
    a clean proposal; several equal-amount candidates propose the oldest with
    ambiguous=True; no candidate means no match.
    """
    if direction != "out":
        return None
    candidates = [draw for draw in pending_draws if draw.amount_thb == amount_thb]
    if not candidates:
        return None
    if len(candidates) == 1:
        return MatchProposal(draw_id=candidates[0].id, ambiguous=False)
    oldest = min(candidates, key=lambda draw: (draw.requested_at, str(draw.id)))
    return MatchProposal(draw_id=oldest.id, ambiguous=True)

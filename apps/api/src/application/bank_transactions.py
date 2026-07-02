"""M1 bank-alert reconciliation use cases: ingest, match, confirm, ignore."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from src.application.errors import NotFoundError, UnrecognizedBankAlertError
from src.application.renovation import RenovationUseCases
from src.application.repositories import (
    AuditWriter,
    BankTransactionRepository,
    BankTransactionRow,
)
from src.domain.bank_alerts import alert_dedup_hash, parse_alert
from src.domain.draw_matching import PendingDraw, propose_match
from src.domain.draws import DrawStatus
from src.domain.errors import BankTransactionRuleError

MAX_LIST_LIMIT = 500

# Bank-transaction reconciliation states.
UNMATCHED = "unmatched"
MATCHED = "matched"
CONFIRMED = "confirmed"
IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class IngestResult:
    transaction: BankTransactionRow
    created: bool  # False when the dedup hash hit an existing row


class BankTransactionUseCases:
    def __init__(
        self,
        repo: BankTransactionRepository,
        audit: AuditWriter,
        renovation: RenovationUseCases,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._renovation = renovation

    async def ingest_alert(self, raw_text: str, source: str, actor: str) -> IngestResult:
        parsed = parse_alert(raw_text)
        if parsed is None:
            raise UnrecognizedBankAlertError()

        dedup_hash = alert_dedup_hash(raw_text)
        existing = await self._repo.get_by_dedup_hash(dedup_hash)
        if existing is not None:
            return IngestResult(transaction=existing, created=False)

        proposal = None
        if parsed.direction == "out":
            pending = [
                PendingDraw(id=d.id, amount_thb=d.amount_thb, requested_at=d.requested_at)
                for d in await self._repo.list_pending_draws()
            ]
            proposal = propose_match(parsed.direction, parsed.amount_thb, pending)

        transaction = await self._repo.create(
            occurred_at=parsed.occurred_at or datetime.now(UTC),
            amount_thb=parsed.amount_thb,
            direction=parsed.direction,
            bank=parsed.bank,
            account_tail=parsed.account_tail,
            raw_text=raw_text,
            source=source,
            status=MATCHED if proposal else UNMATCHED,
            matched_draw_id=proposal.draw_id if proposal else None,
            ambiguous_match=proposal.ambiguous if proposal else False,
            dedup_hash=dedup_hash,
        )
        await self._audit.write(
            actor,
            "bank_transaction.ingested",
            "bank_transactions",
            transaction.id,
            {
                "amount_thb": str(parsed.amount_thb),
                "direction": parsed.direction,
                "bank": parsed.bank,
                "source": source,
                "status": transaction.status,
                "matched_draw_id": (
                    str(transaction.matched_draw_id) if transaction.matched_draw_id else None
                ),
            },
        )
        return IngestResult(transaction=transaction, created=True)

    async def list_transactions(
        self, status: str | None, limit: int
    ) -> Sequence[BankTransactionRow]:
        return await self._repo.list(status, max(1, min(limit, MAX_LIST_LIMIT)))

    async def confirm(self, tx_id: uuid.UUID, actor: str) -> BankTransactionRow:
        transaction = await self._get(tx_id)
        if transaction.status == CONFIRMED:
            raise BankTransactionRuleError("Transaction is already confirmed")
        if transaction.matched_draw_id is None:
            raise BankTransactionRuleError(
                "Transaction has no matched draw; match it before confirming"
            )
        # Reuses the draw-payment use case: validates the draw is payable and
        # writes its own 'draw.paid' audit row.
        await self._renovation.pay_draw(
            transaction.matched_draw_id, actor, paid_at=transaction.occurred_at
        )
        updated = await self._repo.set_status(tx_id, CONFIRMED)
        await self._audit.write(
            actor,
            "bank_transaction.confirmed",
            "bank_transactions",
            tx_id,
            {
                "status": {"from": transaction.status, "to": CONFIRMED},
                "draw_id": str(transaction.matched_draw_id),
            },
        )
        return updated

    async def ignore(self, tx_id: uuid.UUID, actor: str) -> BankTransactionRow:
        transaction = await self._get(tx_id)
        if transaction.status == CONFIRMED:
            raise BankTransactionRuleError("Confirmed transactions cannot be ignored")
        updated = await self._repo.set_status(tx_id, IGNORED)
        await self._audit.write(
            actor,
            "bank_transaction.ignored",
            "bank_transactions",
            tx_id,
            {"status": {"from": transaction.status, "to": IGNORED}},
        )
        return updated

    async def match(self, tx_id: uuid.UUID, draw_id: uuid.UUID, actor: str) -> BankTransactionRow:
        transaction = await self._get(tx_id)
        if transaction.status == CONFIRMED:
            raise BankTransactionRuleError("Confirmed transactions cannot be re-matched")
        if transaction.direction != "out":
            raise BankTransactionRuleError("Only outgoing transactions can match draws")
        draw = await self._repo.get_draw(draw_id)
        if draw is None:
            raise NotFoundError("draw", draw_id)
        if draw.status != DrawStatus.PENDING.value:
            raise BankTransactionRuleError(
                f"Draw {draw_id} is {draw.status}; only pending draws can be matched"
            )
        updated = await self._repo.set_match(
            tx_id, status=MATCHED, matched_draw_id=draw_id, ambiguous_match=False
        )
        await self._audit.write(
            actor,
            "bank_transaction.matched",
            "bank_transactions",
            tx_id,
            {
                "status": {"from": transaction.status, "to": MATCHED},
                "draw_id": str(draw_id),
                "manual": True,
            },
        )
        return updated

    async def _get(self, tx_id: uuid.UUID) -> BankTransactionRow:
        transaction = await self._repo.get(tx_id)
        if transaction is None:
            raise NotFoundError("bank_transaction", tx_id)
        return transaction

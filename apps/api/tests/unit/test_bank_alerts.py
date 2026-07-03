"""Thai bank-alert parser: pure text extraction, no I/O."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from src.domain.bank_alerts import (
    BANGKOK_TZ,
    alert_dedup_hash,
    normalize_alert_text,
    parse_alert,
)


class TestOutgoingAlerts:
    def test_kbank_out_with_masked_account(self) -> None:
        alert = parse_alert(
            "KBank แจ้งเตือน: เงินออกจากบัญชี X-1234 จำนวน 50,000.00 บาท " "วันที่ 02/07/2569 14:30"
        )
        assert alert is not None
        assert alert.direction == "out"
        assert alert.amount_thb == Decimal("50000.00")
        assert alert.bank == "kbank"
        assert alert.account_tail == "1234"

    def test_kbank_debit_wording(self) -> None:
        alert = parse_alert("กสิกรไทย รายการหักบัญชี xxx-x-x5678 จำนวนเงิน 12,345.67 บาท")
        assert alert is not None
        assert alert.direction == "out"
        assert alert.amount_thb == Decimal("12345.67")
        assert alert.bank == "kbank"
        assert alert.account_tail == "5678"

    def test_scb_transfer_with_thb_label(self) -> None:
        alert = parse_alert("SCB รายการโอนเงินสำเร็จ จาก บัญชี xxx-x-x9876 จำนวนเงิน (THB) 250,000.00")
        assert alert is not None
        assert alert.direction == "out"
        assert alert.amount_thb == Decimal("250000.00")
        assert alert.bank == "scb"
        assert alert.account_tail == "9876"

    def test_bangkok_bank_out(self) -> None:
        alert = parse_alert("ธนาคารกรุงเทพ โอนเงินออกจากบัญชี ...4321 จำนวน 75,500 บาท")
        assert alert is not None
        assert alert.direction == "out"
        assert alert.amount_thb == Decimal("75500.00")
        assert alert.bank == "bbl"
        assert alert.account_tail == "4321"

    def test_english_fallback(self) -> None:
        alert = parse_alert("Krungsri alert: Transfer of THB 30,000.00 from account x2468")
        assert alert is not None
        assert alert.direction == "out"
        assert alert.amount_thb == Decimal("30000.00")
        assert alert.bank == "krungsri"
        assert alert.account_tail == "2468"


class TestIncomingAlerts:
    def test_kbank_money_in(self) -> None:
        alert = parse_alert("K PLUS เงินเข้าบัญชี X-1234 จำนวน 5,000.00 บาท")
        assert alert is not None
        assert alert.direction == "in"
        assert alert.amount_thb == Decimal("5000.00")

    def test_received_transfer(self) -> None:
        alert = parse_alert("กรุงไทย รับโอนเงิน เข้าบัญชี ...1111 จำนวน 999.50 บาท")
        assert alert is not None
        assert alert.direction == "in"
        assert alert.bank == "ktb"
        assert alert.amount_thb == Decimal("999.50")


class TestAmounts:
    def test_amount_without_decimals_quantized_to_satang(self) -> None:
        alert = parse_alert("เงินออกจากบัญชี X-1 จำนวน 1,000,000 บาท")
        assert alert is not None
        assert alert.amount_thb == Decimal("1000000.00")

    def test_satang_preserved(self) -> None:
        alert = parse_alert("เงินออกจากบัญชี X-1 จำนวน 42.25 บาท")
        assert alert is not None
        assert alert.amount_thb == Decimal("42.25")

    def test_labelled_amount_wins_over_bare_baht_number(self) -> None:
        # The balance line must not be mistaken for the transaction amount.
        alert = parse_alert("เงินออกจากบัญชี X-1234 จำนวนเงิน 500.00 บาท คงเหลือ 99,999.99 บาท")
        assert alert is not None
        assert alert.amount_thb == Decimal("500.00")


class TestDates:
    def test_buddhist_era_converted(self) -> None:
        alert = parse_alert("เงินออกจากบัญชี X-1 จำนวน 100 บาท วันที่ 02/07/2569 14:30")
        assert alert is not None
        assert alert.occurred_at == datetime(2026, 7, 2, 14, 30, tzinfo=BANGKOK_TZ)

    def test_common_era_kept(self) -> None:
        alert = parse_alert("Transfer THB 100 from account x1 on 02/07/2026 09:15")
        assert alert is not None
        assert alert.occurred_at == datetime(2026, 7, 2, 9, 15, tzinfo=BANGKOK_TZ)

    def test_missing_date_is_none(self) -> None:
        alert = parse_alert("เงินออกจากบัญชี X-1 จำนวน 100 บาท")
        assert alert is not None
        assert alert.occurred_at is None


class TestRejection:
    @pytest.mark.parametrize(
        "text",
        [
            "รหัส OTP ของคุณคือ 123456 ใช้ได้ 5 นาที",
            "Your verification code is 987654",
            "โปรโมชั่นพิเศษ! รับดอกเบี้ย 5,000 บาท เมื่อเปิดบัญชีใหม่",
            "เช็คยอดบัญชี: คงเหลือ 12,345.00 บาท",
            "สวัสดีครับ นัดดูงานพรุ่งนี้ 10 โมง",
            "",
        ],
    )
    def test_non_transaction_text_returns_none(self, text: str) -> None:
        assert parse_alert(text) is None

    def test_transaction_without_amount_returns_none(self) -> None:
        assert parse_alert("เงินออกจากบัญชี X-1234") is None


class TestDedup:
    def test_whitespace_variants_hash_identically(self) -> None:
        a = "เงินออกจากบัญชี X-1  จำนวน 100 บาท"
        b = "เงินออกจากบัญชี   X-1 จำนวน\n100 บาท "
        assert normalize_alert_text(a) == normalize_alert_text(b)
        assert alert_dedup_hash(a) == alert_dedup_hash(b)

    def test_different_content_hashes_differently(self) -> None:
        assert alert_dedup_hash("จำนวน 100 บาท") != alert_dedup_hash("จำนวน 101 บาท")

"""Unit tests for the compliance gate — no network."""

import pytest

from collectors.compliance import (
    ComplianceGate,
    ComplianceViolation,
    InMemoryRateLimiter,
    SourcePolicy,
    TosPolicy,
)


def make_policy(**overrides) -> SourcePolicy:
    defaults = dict(
        name="test-source",
        tos_policy=TosPolicy.ALLOWED,
        rate_limit_per_hr=60,
        enabled=True,
    )
    defaults.update(overrides)
    return SourcePolicy(**defaults)


class TestCheckUrl:
    def setup_method(self) -> None:
        self.gate = ComplianceGate()

    def test_allowed_source_passes(self) -> None:
        self.gate.check_url(make_policy(), "https://example.com/feed.xml")

    @pytest.mark.parametrize(
        "url",
        [
            "https://facebook.com/somepage",
            "https://www.facebook.com/groups/x",
            "https://m.facebook.com/x",
            "https://airbnb.com/rooms/1",
            "https://www.booking.com/hotel/th/x.html",
            "https://agoda.com/x",
            "https://instagram.com/x",
        ],
    )
    def test_hard_blocklist_refused_even_when_registry_allows(self, url: str) -> None:
        with pytest.raises(ComplianceViolation) as exc:
            self.gate.check_url(make_policy(), url)
        assert exc.value.reason == "hard_blocklist"

    def test_lookalike_domains_are_not_blocked(self) -> None:
        # notfacebook.com must not suffix-match facebook.com
        self.gate.check_url(make_policy(), "https://notfacebook.com/x")

    def test_prohibited_tos_policy_refused(self) -> None:
        with pytest.raises(ComplianceViolation) as exc:
            self.gate.check_url(
                make_policy(tos_policy=TosPolicy.PROHIBITED), "https://example.com"
            )
        assert exc.value.reason == "tos_policy"

    def test_review_tos_policy_refused(self) -> None:
        with pytest.raises(ComplianceViolation):
            self.gate.check_url(make_policy(tos_policy=TosPolicy.REVIEW), "https://example.com")

    def test_disabled_source_refused(self) -> None:
        with pytest.raises(ComplianceViolation) as exc:
            self.gate.check_url(make_policy(enabled=False), "https://example.com")
        assert exc.value.reason == "source_disabled"

    @pytest.mark.parametrize("url", ["ftp://example.com/x", "not-a-url", "file:///etc/passwd"])
    def test_non_http_urls_refused(self, url: str) -> None:
        with pytest.raises(ComplianceViolation) as exc:
            self.gate.check_url(make_policy(), url)
        assert exc.value.reason == "invalid_url"


class TestRateLimiter:
    def test_allows_up_to_capacity_then_refuses(self) -> None:
        limiter = InMemoryRateLimiter()
        allowed = [limiter.acquire("k", per_hour=5) for _ in range(6)]
        assert allowed == [True, True, True, True, True, False]

    def test_keys_are_independent(self) -> None:
        limiter = InMemoryRateLimiter()
        assert all(limiter.acquire("a", per_hour=1) for _ in range(1))
        assert limiter.acquire("b", per_hour=1)

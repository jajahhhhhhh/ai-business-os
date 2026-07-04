"""Reddit collector: listing parse + auth/config gating. No network."""

from __future__ import annotations

import json

import pytest

from collectors.compliance import ComplianceGate, SourcePolicy, TosPolicy
from collectors.reddit import RedditCollector


def make_policy() -> SourcePolicy:
    return SourcePolicy(name="r/kohsamui", tos_policy=TosPolicy.ALLOWED, rate_limit_per_hr=12)


LISTING = {
    "data": {
        "children": [
            {
                "data": {
                    "author": "traveler42",
                    "title": "Looking for a villa in Koh Samui for 2 weeks in August",
                    "selftext": "Family of 4, budget around 5000 THB/night, near Lipa Noi.",
                    "permalink": "/r/kohsamui/comments/abc/looking_for_a_villa/",
                }
            },
            {
                "data": {
                    "author": "[deleted]",
                    "title": "Deleted post",
                    "selftext": "",
                    "permalink": "/r/kohsamui/comments/ddd/x/",
                }
            },
            {
                "data": {
                    "author": "nopermalink",
                    "title": "No permalink",
                    "selftext": "",
                    "permalink": "",
                }
            },
        ]
    }
}


class TestParseListing:
    def make(self) -> RedditCollector:
        return RedditCollector(
            ComplianceGate(), make_policy(), "r/KohSamui", client_id="x", client_secret="y"
        )

    def test_posts_become_documents_with_handle_first(self) -> None:
        docs = self.make()._parse_listing(json.dumps(LISTING))
        assert len(docs) == 1
        doc = docs[0]
        assert doc.content.startswith("u/traveler42\n")
        assert "Looking for a villa" in doc.content
        assert "5000 THB/night" in doc.content
        assert doc.url == "https://www.reddit.com/r/kohsamui/comments/abc/looking_for_a_villa/"
        assert doc.source_name == "r/kohsamui"

    def test_deleted_and_broken_posts_skipped(self) -> None:
        docs = self.make()._parse_listing(json.dumps(LISTING))
        assert all("[deleted]" not in d.content for d in docs)
        assert len(docs) == 1

    def test_empty_listing(self) -> None:
        assert self.make()._parse_listing(json.dumps({"data": {"children": []}})) == []

    def test_subreddit_normalized(self) -> None:
        collector = RedditCollector(
            ComplianceGate(), make_policy(), "r/KohSamui/", client_id="x", client_secret="y"
        )
        assert collector._subreddit == "kohsamui"


class TestConfigGating:
    @pytest.mark.asyncio
    async def test_unconfigured_collector_fetches_nothing(self) -> None:
        collector = RedditCollector(ComplianceGate(), make_policy(), "kohsamui")
        assert collector.is_configured is False
        assert await collector.fetch() == []

"""RSS/Atom collector — the first production source type (§8.4: ✅ allowed).

Parses with the stdlib to keep the dependency surface minimal; upgrade to
``feedparser`` only if malformed feeds show up in practice (tracked in
docs/tech-debt.md).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from collectors.base import RawDocument
from collectors.compliance import ComplianceGate, SourcePolicy

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class RssCollector:
    def __init__(self, gate: ComplianceGate, policy: SourcePolicy, feed_url: str) -> None:
        self.source_name = policy.name
        self._gate = gate
        self._policy = policy
        self._feed_url = feed_url

    async def fetch(self) -> list[RawDocument]:
        body = await self._gate.fetch(self._policy, self._feed_url)
        return self._parse(body)

    def _parse(self, body: str) -> list[RawDocument]:
        root = ET.fromstring(body)
        docs: list[RawDocument] = []
        # RSS 2.0
        for item in root.iter("item"):
            docs.append(self._to_doc(item, title="title", link="link", desc="description"))
        # Atom
        for entry in root.iter(f"{_ATOM_NS}entry"):
            title = entry.findtext(f"{_ATOM_NS}title") or ""
            link_el = entry.find(f"{_ATOM_NS}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = (
                entry.findtext(f"{_ATOM_NS}summary") or entry.findtext(f"{_ATOM_NS}content") or ""
            )
            docs.append(
                RawDocument(
                    source_name=self.source_name,
                    url=link or self._feed_url,
                    content=f"{title}\n\n{summary}".strip(),
                )
            )
        return docs

    def _to_doc(self, item: ET.Element, title: str, link: str, desc: str) -> RawDocument:
        return RawDocument(
            source_name=self.source_name,
            url=item.findtext(link) or self._feed_url,
            content=f"{item.findtext(title) or ''}\n\n{item.findtext(desc) or ''}".strip(),
        )

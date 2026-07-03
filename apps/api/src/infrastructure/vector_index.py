"""Qdrant vector index adapter (AsyncQdrantClient).

Collections are created lazily on first upsert (bge-m3: 1024-dim, cosine —
see docs/ARCHITECTURE.md §7). Reads against a missing collection return
empty/no-op instead of raising, so a fresh deployment degrades gracefully.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from src.application.ports import VectorHit, VectorPoint

VECTOR_SIZE = 1024  # bge-m3


def _is_missing_collection(exc: UnexpectedResponse) -> bool:
    return exc.status_code == 404


class QdrantVectorIndex:
    def __init__(self, url: str) -> None:
        # check_compatibility=False: skip the eager version handshake — it only
        # emits a warning at construction time when Qdrant is unreachable.
        self._client = AsyncQdrantClient(url=url, check_compatibility=False)

    async def _ensure_collection(self, collection: str) -> None:
        if not await self._client.collection_exists(collection):
            await self._client.create_collection(
                collection,
                vectors_config=qmodels.VectorParams(
                    size=VECTOR_SIZE, distance=qmodels.Distance.COSINE
                ),
            )

    async def upsert(self, collection: str, points: Sequence[VectorPoint]) -> None:
        if not points:
            return
        await self._ensure_collection(collection)
        await self._client.upsert(
            collection,
            points=[
                qmodels.PointStruct(
                    id=point.id, vector=list(point.vector), payload=dict(point.payload)
                )
                for point in points
            ],
        )

    async def delete_document(self, collection: str, document_id: uuid.UUID) -> None:
        try:
            await self._client.delete(
                collection,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=str(document_id)),
                            )
                        ]
                    )
                ),
            )
        except UnexpectedResponse as exc:
            if not _is_missing_collection(exc):
                raise

    async def delete_points(self, collection: str, ids: Sequence[str]) -> None:
        if not ids:
            return
        try:
            await self._client.delete(
                collection, points_selector=qmodels.PointIdsList(points=list(ids))
            )
        except UnexpectedResponse as exc:
            if not _is_missing_collection(exc):
                raise

    async def search(self, collection: str, vector: Sequence[float], limit: int) -> list[VectorHit]:
        try:
            result = await self._client.query_points(
                collection, query=list(vector), limit=limit, with_payload=True
            )
        except UnexpectedResponse as exc:
            if _is_missing_collection(exc):  # nothing embedded yet
                return []
            raise
        return [
            VectorHit(id=str(point.id), score=float(point.score), payload=dict(point.payload or {}))
            for point in result.points
        ]

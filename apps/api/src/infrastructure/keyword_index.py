"""Meilisearch keyword index over KB chunks, via raw REST (httpx).

Deliberately no meilisearch SDK: httpx is already a core dependency and the
surface we need is four endpoints. Meilisearch tokenizes Thai natively.
Index writes are asynchronous in Meilisearch, so mutating calls wait for
their task to succeed — documents.meili_indexed then reflects reality.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence

import httpx

from src.application.ports import KeywordChunk

INDEX_UID = "kb_chunks"
_TASK_POLL_SECONDS = 0.2
_TASK_TIMEOUT_SECONDS = 60.0
_HTTP_TIMEOUT_SECONDS = 30.0


class MeilisearchKeywordIndex:
    def __init__(self, base_url: str, master_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {master_key}"} if master_key else {}
        self._settings_pushed = False

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=_HTTP_TIMEOUT_SECONDS
        )

    async def _wait_for_task(self, client: httpx.AsyncClient, task_uid: int) -> None:
        deadline = time.monotonic() + _TASK_TIMEOUT_SECONDS
        while True:
            response = await client.get(f"/tasks/{task_uid}")
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status")
            if status == "succeeded":
                return
            if status in ("failed", "canceled"):
                raise RuntimeError(f"meilisearch task {task_uid} {status}: {payload.get('error')}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"meilisearch task {task_uid} still {status}")
            await asyncio.sleep(_TASK_POLL_SECONDS)

    async def _ensure_settings(self, client: httpx.AsyncClient) -> None:
        """Create the index (explicit primary key) and make document_id
        filterable. Idempotent, pushed once per process.

        The index is created with an EXPLICIT primaryKey='id': chunk records
        carry both `id` and `document_id`, and Meilisearch primary-key
        inference fails when it finds more than one `*id` field. Relying on
        inference (or on a bare settings PATCH, which creates the index with
        no key) leaves the index un-writable and every ingest fails.
        """
        if self._settings_pushed:
            return
        # Create only if absent — POST on an existing index yields a task that
        # fails with index_already_exists, which we'd otherwise treat as fatal.
        exists = await client.get(f"/indexes/{INDEX_UID}")
        if exists.status_code == 404:
            created = await client.post(
                "/indexes", json={"uid": INDEX_UID, "primaryKey": "id"}
            )
            created.raise_for_status()
            await self._wait_for_task(client, created.json()["taskUid"])
        elif exists.status_code >= 400:
            exists.raise_for_status()
        response = await client.patch(
            f"/indexes/{INDEX_UID}/settings",
            json={"filterableAttributes": ["document_id"]},
        )
        response.raise_for_status()
        await self._wait_for_task(client, response.json()["taskUid"])
        self._settings_pushed = True

    async def index_chunks(self, chunks: Sequence[KeywordChunk]) -> None:
        documents = [
            {
                "id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "document_title": chunk.document_title,
                "lang": chunk.lang,
                "seq": chunk.seq,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
        if not documents:
            return
        async with self._client() as client:
            await self._ensure_settings(client)
            response = await client.put(f"/indexes/{INDEX_UID}/documents", json=documents)
            response.raise_for_status()
            await self._wait_for_task(client, response.json()["taskUid"])

    async def delete_document(self, document_id: uuid.UUID) -> None:
        async with self._client() as client:
            # The pipeline deletes stale chunks before indexing new ones; on a
            # fresh index the delete would otherwise be accepted (202) and then
            # fail its task with index_not_found, killing ingestion. Ensure the
            # index exists first.
            await self._ensure_settings(client)
            response = await client.post(
                f"/indexes/{INDEX_UID}/documents/delete",
                json={"filter": f'document_id = "{document_id}"'},
            )
            if response.status_code == 404:  # index not created yet: nothing to delete
                return
            response.raise_for_status()
            await self._wait_for_task(client, response.json()["taskUid"])

    async def search(self, q: str, limit: int) -> list[str]:
        async with self._client() as client:
            response = await client.post(
                f"/indexes/{INDEX_UID}/search",
                json={"q": q, "limit": limit, "attributesToRetrieve": ["id"]},
            )
            if response.status_code == 404:  # no documents indexed yet
                return []
            response.raise_for_status()
            return [hit["id"] for hit in response.json().get("hits", [])]

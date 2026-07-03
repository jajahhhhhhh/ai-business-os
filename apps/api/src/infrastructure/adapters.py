"""Construction of the KB/memory gateway adapters from settings.

Shared by the API factory (src/main.py) and the Celery worker (src/worker.py)
so the wiring exists in exactly one place.

Test seam: integration tests build a KbAdapters out of in-memory fakes
(tests/fakes.py) and pass it to create_app(kb_adapters=...). A constructor
override was chosen over FastAPI dependency_overrides because the worker
pipeline and BackgroundTasks fallback need the same injection point, and
dependency_overrides only covers HTTP request handling.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.ports import (
    Embedder,
    KeywordIndex,
    ObjectStorage,
    TextExtractor,
    VectorIndex,
)
from src.config import Settings
from src.infrastructure.embeddings import BgeM3Embedder
from src.infrastructure.keyword_index import MeilisearchKeywordIndex
from src.infrastructure.object_storage import S3ObjectStorage
from src.infrastructure.parsing import extract_text
from src.infrastructure.vector_index import QdrantVectorIndex


@dataclass(slots=True)
class KbAdapters:
    """The gateway set used by KB + memory use cases (fields are ports)."""

    storage: ObjectStorage
    keyword_index: KeywordIndex
    vector_index: VectorIndex
    embedder: Embedder
    extract: TextExtractor


def build_kb_adapters(settings: Settings) -> KbAdapters:
    return KbAdapters(
        storage=S3ObjectStorage(
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_bucket,
        ),
        keyword_index=MeilisearchKeywordIndex(settings.meili_url, settings.meili_master_key),
        vector_index=QdrantVectorIndex(settings.qdrant_url),
        embedder=BgeM3Embedder(settings.embedding_model),
        extract=extract_text,
    )

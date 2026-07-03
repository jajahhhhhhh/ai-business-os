"""bge-m3 embeddings via sentence-transformers (the optional `ml` extra).

sentence-transformers (and its torch dependency) is imported LAZILY inside
the encode path so the core service imports and runs without it installed.
`is_available` reports whether the extra is importable; callers (KB/memory
use cases) skip semantic indexing/search and degrade gracefully when False.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Sequence
from typing import Any

DEFAULT_MODEL = "BAAI/bge-m3"


class BgeM3Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any | None = None

    @property
    def is_available(self) -> bool:
        return importlib.util.find_spec("sentence_transformers") is not None

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy: `ml` extra

            self._model = SentenceTransformer(self._model_name)
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        # Model load + encode are CPU/GPU-bound; keep the event loop free.
        return await asyncio.to_thread(self._encode, [str(text) for text in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

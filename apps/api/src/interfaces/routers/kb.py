"""Knowledge-base endpoints: document upload/listing and hybrid search (M2)."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.kb import KnowledgeBaseUseCases
from src.infrastructure.adapters import KbAdapters
from src.infrastructure.audit import SqlAuditWriter
from src.infrastructure.repositories import KnowledgeBaseSqlRepository
from src.interfaces.dependencies import (
    KbAdaptersDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
)
from src.interfaces.problems import ProblemError
from src.interfaces.schemas import (
    DocumentDetailOut,
    DocumentOut,
    DocumentStatus,
    SearchMode,
    SearchOut,
    SearchResultOut,
)

logger = structlog.get_logger("api.kb")

router = APIRouter(prefix="/kb", tags=["kb"])

PROCESS_TASK = "src.worker.process_document"


def _use_cases(session: AsyncSession, adapters: KbAdapters) -> KnowledgeBaseUseCases:
    return KnowledgeBaseUseCases(
        KnowledgeBaseSqlRepository(session),
        SqlAuditWriter(session),
        storage=adapters.storage,
        keyword_index=adapters.keyword_index,
        vector_index=adapters.vector_index,
        embedder=adapters.embedder,
        extract=adapters.extract,
    )


async def _process_inline(request: Request, document_id: uuid.UUID) -> None:
    """BackgroundTasks fallback when the Celery broker is unreachable.

    Tradeoff: this blocks one API worker for the duration of the pipeline
    (OCR-heavy PDFs can take minutes) and dies with the process — no retry,
    no queue backpressure. Acceptable as a degraded mode so uploads still get
    indexed on a single-node deployment with Redis down; the broker path is
    the production one.
    """
    from src.worker import run_document_pipeline  # local import: keeps startup light

    await run_document_pipeline(
        document_id,
        maker=request.app.state.sessionmaker,
        adapters=request.app.state.kb_adapters,
    )


@router.post("/documents", response_model=DocumentOut, status_code=202)
async def upload_document(
    file: UploadFile,
    session: SessionDep,
    settings: SettingsDep,
    adapters: KbAdaptersDep,
    principal: PrincipalDep,
    request: Request,
    background: BackgroundTasks,
    title: Annotated[str | None, Form()] = None,
    lang: Annotated[str | None, Form()] = None,
) -> DocumentOut:
    data = await file.read()
    max_bytes = settings.kb_max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ProblemError(
            status=413,
            title="Content Too Large",
            detail=f"Upload exceeds the {settings.kb_max_upload_mb} MB limit",
        )
    use_cases = _use_cases(session, adapters)
    document = await use_cases.ingest_document(
        data=data,
        filename=file.filename or "document",
        mime=file.content_type or "application/octet-stream",
        title=title,
        lang=lang,
        source="upload",
        actor=principal.actor,
    )
    # Commit BEFORE dispatching so the worker's own session can see the row.
    await session.commit()

    try:
        from src.worker import celery_app  # local import, same seam as jobs.py

        celery_app.send_task(PROCESS_TASK, args=[str(document.id)], retry=False)
    except Exception:  # noqa: BLE001 - broker down must not fail the upload
        logger.warning("kb_dispatch_failed", document_id=str(document.id))
        background.add_task(_process_inline, request, document.id)
    return DocumentOut.model_validate(document)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    session: SessionDep,
    adapters: KbAdaptersDep,
    status: Annotated[DocumentStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DocumentOut]:
    documents = await _use_cases(session, adapters).list_documents(status, limit)
    return [DocumentOut.model_validate(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: uuid.UUID, session: SessionDep, adapters: KbAdaptersDep
) -> DocumentDetailOut:
    detail = await _use_cases(session, adapters).get_document(document_id)
    base = DocumentOut.model_validate(detail.document)
    return DocumentDetailOut(**base.model_dump(), chunk_count=detail.chunk_count)


@router.get("/search", response_model=SearchOut)
async def search(
    session: SessionDep,
    adapters: KbAdaptersDep,
    q: Annotated[str, Query(min_length=1, max_length=1_000)],
    mode: Annotated[SearchMode, Query()] = "hybrid",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> SearchOut:
    results = await _use_cases(session, adapters).search(q, mode=mode, limit=limit)
    return SearchOut(
        query=results.query,
        mode=results.mode,  # type: ignore[arg-type]
        degraded=results.degraded,
        results=[
            SearchResultOut(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                document_title=item.document_title,
                seq=item.seq,
                text=item.text,
                score=item.score,
                matched_by=list(item.matched_by),
            )
            for item in results.results
        ],
    )

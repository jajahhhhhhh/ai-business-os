"""RFC 9457 problem+json error responses via shared exception handlers."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.application.errors import (
    ComplianceRefusedError,
    NotFoundError,
    UnrecognizedBankAlertError,
)
from src.domain.errors import (
    BankTransactionRuleError,
    CurrencyMismatchError,
    DomainError,
    DrawRuleError,
    InvalidCursorError,
    InvalidScoreError,
    InvalidStageTransitionError,
)

PROBLEM_CONTENT_TYPE = "application/problem+json"

logger = structlog.get_logger("api.errors")


class ProblemError(Exception):
    """Raise anywhere in the interface layer to short-circuit into problem+json."""

    def __init__(
        self,
        status: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.headers = headers
        super().__init__(detail or title)


def problem_response(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "instance": request.url.path,
    }
    if detail is not None:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=status, content=body, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


_DOMAIN_STATUS: tuple[tuple[type[DomainError], int], ...] = (
    (InvalidCursorError, 400),
    (InvalidScoreError, 422),
    (InvalidStageTransitionError, 409),
    (DrawRuleError, 409),
    (CurrencyMismatchError, 409),
    (BankTransactionRuleError, 409),
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem_error(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            request,
            status=exc.status,
            title=exc.title,
            detail=exc.detail,
            type_=exc.type,
            headers=exc.headers,
        )

    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return problem_response(request, status=404, title="Not Found", detail=str(exc))

    @app.exception_handler(ComplianceRefusedError)
    async def _compliance_refused(request: Request, exc: ComplianceRefusedError) -> JSONResponse:
        return problem_response(request, status=422, title="Unprocessable Entity", detail=str(exc))

    @app.exception_handler(UnrecognizedBankAlertError)
    async def _unrecognized_alert(
        request: Request, exc: UnrecognizedBankAlertError
    ) -> JSONResponse:
        return problem_response(request, status=422, title="Unprocessable Entity", detail=str(exc))

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status = next((s for t, s in _DOMAIN_STATUS if isinstance(exc, t)), 422)
        return problem_response(
            request, status=status, title=HTTPStatus(status).phrase, detail=str(exc)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            request,
            status=422,
            title="Unprocessable Entity",
            detail="Request validation failed",
            extra={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "Error"
        return problem_response(
            request,
            status=exc.status_code,
            title=title,
            detail=str(exc.detail) if exc.detail else None,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path)
        return problem_response(
            request,
            status=500,
            title="Internal Server Error",
            detail="An unexpected error occurred",
        )

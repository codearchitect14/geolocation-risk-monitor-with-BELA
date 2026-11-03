"""RFC 7807 problem responses. Details never include stack traces, SQL, or request values."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("meridian.api")
PROBLEM = "application/problem+json"
TITLES = {
    400: "Bad request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Payload too large",
    415: "Unsupported media type",
    422: "Validation failed",
    429: "Too many requests",
    500: "Internal error",
    503: "Service unavailable",
}


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        detail: str,
        *,
        title: str | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status, self.detail, self.title = status, detail, title or TITLES.get(status, "Error")
        self.code, self.headers, self.extra = code, headers or {}, extra or {}


def problem_response(request: Request, status: int, title: str, detail: str, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://meridian.invalid/problems/{extra.pop('code', None) or title.lower().replace(' ', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def install(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        response = problem_response(request, exc.status, exc.title, exc.detail, code=exc.code, **exc.extra)
        response.headers.update(exc.headers)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else TITLES.get(exc.status_code, "Error")
        response = problem_response(request, exc.status_code, TITLES.get(exc.status_code, "Error"), detail)
        response.headers.update(dict(exc.headers or {}))
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        return problem_response(request, 422, TITLES[422], "The request failed validation.", errors=errors)

    @app.exception_handler(psycopg.Error)
    async def _database(request: Request, exc: psycopg.Error) -> JSONResponse:
        """Constraint failures become client errors without echoing database messages."""
        if isinstance(exc, pg_errors.UniqueViolation):
            return problem_response(
                request, 409, TITLES[409], "A record with these values already exists.", code="duplicate"
            )
        if isinstance(exc, pg_errors.NotNullViolation):
            return problem_response(
                request,
                422,
                TITLES[422],
                "A required value is missing. Platform administrators must send X-Tenant-Id to act inside a tenant.",
                code="missing-value",
            )
        if isinstance(
            exc,
            pg_errors.ForeignKeyViolation
            | pg_errors.CheckViolation
            | pg_errors.DataError
            | pg_errors.InvalidTextRepresentation,
        ):
            return problem_response(
                request, 422, TITLES[422], "The request refers to a value that is not allowed.", code="invalid-value"
            )
        if isinstance(exc, pg_errors.InsufficientPrivilege):
            return problem_response(
                request, 403, TITLES[403], "You do not have permission to perform this action.", code="forbidden"
            )
        log.error(
            "database error request_id=%s type=%s", getattr(request.state, "request_id", None), type(exc).__name__
        )
        return problem_response(request, 500, TITLES[500], "The request could not be completed.")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled error request_id=%s type=%s", getattr(request.state, "request_id", None), type(exc).__name__
        )
        return problem_response(request, 500, TITLES[500], "The request could not be completed.")

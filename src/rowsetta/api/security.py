import logging
import os
import secrets
from dataclasses import dataclass
from http import HTTPStatus
from typing import Self

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from rowsetta.api.errors import ApiError, error_body

COOKIE_NAME = "rowsetta_session"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class SessionSecurity:
    """One launch's authentication secret; never included in workspace state."""

    token: str

    @classmethod
    def for_host(cls, host: str) -> Self:
        """Allow deterministic test tokens only on the loopback bind address."""
        token = os.environ.get("ROWSETTA_SESSION_TOKEN")
        if token is not None and host != "127.0.0.1":
            message = "ROWSETTA_SESSION_TOKEN is only allowed on 127.0.0.1"
            raise ValueError(message)
        if token == "":
            message = "ROWSETTA_SESSION_TOKEN must not be empty"
            raise ValueError(message)
        return cls(token if token is not None else secrets.token_urlsafe(32))


class SessionMiddleware(BaseHTTPMiddleware):
    """Exchange the launch URL once, then authenticate requests using an HTTP-only cookie."""

    def __init__(self, app: ASGIApp, *, security: SessionSecurity) -> None:
        super().__init__(app)
        self._security = security

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Keep health public and reject missing or incorrect launch credentials."""
        if request.url.path == "/health":
            return await call_next(request)
        # Cookies share a host across ports; each listening instance needs its own.
        cookie_name = f"{COOKIE_NAME}_{request.url.port or 80}"
        token = request.query_params.get("token") if request.url.path == "/" else None
        if token is not None:
            if not secrets.compare_digest(token.encode(), self._security.token.encode()):
                return _forbidden()
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(cookie_name, self._security.token, httponly=True, samesite="strict")
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            return response
        cookie = request.cookies.get(cookie_name, "")
        if not secrets.compare_digest(cookie.encode(), self._security.token.encode()):
            return _forbidden()
        return await call_next(request)


class ErrorContractMiddleware(BaseHTTPMiddleware):
    """Cover framework middleware failures and unexpected server errors with recovery text."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Return actionable JSON without exposing exception details or request secrets."""
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger(__name__).exception("Request failed")
            error = ApiError("The request could not be completed.", status_code=500)
            return JSONResponse(error_body(error), status_code=500)
        if (
            response.status_code >= HTTPStatus.BAD_REQUEST
            and "application/json" not in response.headers.get("content-type", "")
        ):
            what = (
                "Invalid Host header."
                if response.status_code == HTTPStatus.BAD_REQUEST
                else "The requested resource is unavailable."
            )
            error = ApiError(what, status_code=response.status_code)
            return JSONResponse(error_body(error), status_code=response.status_code)
        return response


def _forbidden() -> JSONResponse:
    error = ApiError("A valid launch session is required.", status_code=403)
    return JSONResponse(error_body(error), status_code=403)

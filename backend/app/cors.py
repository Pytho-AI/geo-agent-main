"""CORS origin parsing, validation, and rejection logging.

Reads ALLOWED_ORIGINS (comma-separated exact origins) AND/OR
ALLOWED_ORIGIN_REGEX (single regex) from environment. Either may be
set; an incoming Origin header is allowed if it matches EITHER the
exact allowlist OR the regex.

For airgapped LAN deployments where analyst PCs sit on the same RFC
1918 subnet as the server, ALLOWED_ORIGIN_REGEX is the right shape —
there's no way to enumerate every client's IP:port in
ALLOWED_ORIGINS. Example value for any localhost / RFC 1918 origin:

    ALLOWED_ORIGIN_REGEX=^https?://(localhost|127\\.0\\.0\\.1|10\\.[0-9.]+|192\\.168\\.[0-9.]+|172\\.(1[6-9]|2[0-9]|3[01])\\.[0-9.]+)(:[0-9]+)?$

Provides CORSRejectionLogMiddleware to WARN-log Origins that match
neither.
"""

import logging
import os
import re
import sys

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

_ORIGIN_RE = re.compile(r"^https?://[a-zA-Z0-9:._-]+$")


def parse_allowed_origins() -> list[str]:
    """Parse and validate ALLOWED_ORIGINS from environment.

    Returns a list of validated origin strings, possibly empty when
    ALLOWED_ORIGIN_REGEX is being used instead. Exits the process
    only when NEITHER variable is set (no cross-origin client could
    ever reach this service).
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    has_regex = bool(os.environ.get("ALLOWED_ORIGIN_REGEX", "").strip())

    if not raw and not has_regex:
        logger.error(
            "Neither ALLOWED_ORIGINS nor ALLOWED_ORIGIN_REGEX is set — "
            "no cross-origin client could reach this service. Set at "
            "least one (ALLOWED_ORIGIN_REGEX is the right shape for "
            "LAN deployments where the client IPs aren't fixed)."
        )
        sys.exit(1)

    if not raw:
        logger.info("CORS: using ALLOWED_ORIGIN_REGEX only (no exact allowlist)")
        return []

    origins: list[str] = []
    for entry in raw.split(","):
        origin = entry.strip()
        if not origin:
            continue
        if origin == "*":
            logger.error("Wildcard origins not allowed in ALLOWED_ORIGINS")
            sys.exit(1)
        if not _ORIGIN_RE.match(origin):
            logger.error("Invalid origin format: %s", origin)
            sys.exit(1)
        origins.append(origin)

    if not origins and not has_regex:
        logger.error("ALLOWED_ORIGINS env var is empty after parsing")
        sys.exit(1)

    logger.info(
        "CORS allowed origins: %s",
        ", ".join(origins) if origins else "(none — regex only)",
    )
    return origins


def parse_allowed_origin_regex():
    """Parse the optional ALLOWED_ORIGIN_REGEX env var.

    Returns the compiled regex (matched against incoming Origin
    headers) or None when unset. Callers should pass the same raw
    string to CORSMiddleware via allow_origin_regex so Starlette
    handles the actual gate, then pass the compiled pattern to
    CORSRejectionLogMiddleware so its logging stays consistent.
    """
    raw = os.environ.get("ALLOWED_ORIGIN_REGEX", "").strip()
    if not raw:
        return None
    try:
        pattern = re.compile(raw)
    except re.error as e:
        logger.error("Invalid ALLOWED_ORIGIN_REGEX %r: %s", raw, e)
        sys.exit(1)
    logger.info("CORS allowed origin regex: %s", raw)
    return pattern


class CORSRejectionLogMiddleware(BaseHTTPMiddleware):
    """Logs WARN when a request's Origin matches NEITHER the exact
    allowlist nor the optional regex.

    Must be added BEFORE CORSMiddleware (i.e. added after it in
    FastAPI's add_middleware calls, since middleware executes in
    reverse order).
    """

    def __init__(
        self,
        app,
        allowed_origins: list[str],
        allowed_origin_regex=None,
    ):
        super().__init__(app)
        self._allowed = set(allowed_origins)
        self._regex = allowed_origin_regex

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in self._allowed and (
            self._regex is None or not self._regex.match(origin)
        ):
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(
                "Rejected CORS request from %s (client: %s, path: %s)",
                origin,
                client_ip,
                request.url.path,
            )
        return await call_next(request)

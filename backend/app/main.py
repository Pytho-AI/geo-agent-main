import logging
import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.cors import (
    parse_allowed_origins,
    parse_allowed_origin_regex,
    CORSRejectionLogMiddleware,
)

# Load .env file for local dev. In production, Docker/K8s sets env vars
# directly and load_dotenv() will not override them.
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Suppress verbose SQLAlchemy engine logs
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Suppress GDAL/rasterio 404 noise from VSICurl tile fetches — these are
# expected misses (e.g. ocean tiles absent from ESA WorldCover) and are
# already handled by the calling code's exception handlers.
logging.getLogger("rasterio").setLevel(logging.WARNING)
logging.getLogger("rasterio._env").setLevel(logging.WARNING)

# Suppress botocore credential INFO spam that fires on every S3 GDAL open
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("botocore.credentials").setLevel(logging.WARNING)

logger = logging.getLogger("app.access")

settings = get_settings()

# Persistent file logging on the data volume, ALONGSIDE stdout (docker
# logs stays useful for live tails; the file survives container
# recreates, which docker logs does not). Everything the process logs
# lands here — request lines, tracebacks (logger.exception), and
# forwarded browser-side errors (the geo.client logger fed by
# POST /api/v1/events/client-log). Rotating so an error loop can never
# fill the volume. Bare dev runs without /app/data just skip it.
try:
    from logging.handlers import RotatingFileHandler
    from pathlib import Path as _Path

    _log_dir = _Path(settings.data_dir) / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _file_handler = RotatingFileHandler(
        _log_dir / "backend.log", maxBytes=20 * 1024 * 1024, backupCount=5,
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(_file_handler)
    logging.getLogger(__name__).info(
        "persistent log file: %s", _log_dir / "backend.log")
except OSError as _log_err:
    logging.getLogger(__name__).warning(
        "persistent file logging disabled: %s", _log_err)

# Parse CORS origins from environment. Either ALLOWED_ORIGINS (exact
# list) or ALLOWED_ORIGIN_REGEX (single regex) may be set; an Origin
# header is allowed if it matches either. For airgapped LAN
# deployments the regex form is the right shape — analyst PCs aren't
# at fixed IPs.
ALLOWED_ORIGINS = parse_allowed_origins()
ALLOWED_ORIGIN_REGEX = parse_allowed_origin_regex()
_ALLOWED_ORIGIN_REGEX_STR = os.environ.get("ALLOWED_ORIGIN_REGEX", "").strip() or None


@asynccontextmanager
async def lifespan(_app):
    if settings.offline_mode:
        from app.services.knowledge.roads import _load_offline_roads
        _load_offline_roads()
    # Entity graph: schema + versioned reference seeds (registries,
    # WEG catalog extracts, force templates). Idempotent.
    try:
        from app.db.bootstrap import bootstrap_entity_graph
        await bootstrap_entity_graph()
        # Product engine startup sweep: queued/running records fail
        # visibly with engine_restart — no ghosts survive a deploy.
        from app.services.products.engine import startup_sweep
        await startup_sweep()
    except Exception as e:
        logging.getLogger(__name__).warning("entity-graph bootstrap skipped: %s", e)
    # Idempotent bootstrap for tables added after init-db.sql first ran on
    # existing deployments. New fresh installs already get this from
    # infra/scripts/init-db.sql; this catches DBs already provisioned.
    try:
        from sqlalchemy import text
        from app.db.session import engine
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS custom_symbols (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(255) NOT NULL,
                    file_format VARCHAR(10) NOT NULL,
                    mime_type VARCHAR(100) NOT NULL,
                    storage_uri VARCHAR(1024) NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    created_by VARCHAR(255),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS analyst_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    occurred_at_ms BIGINT,
                    received_at_ms BIGINT NOT NULL,
                    user_id VARCHAR(255),
                    map_id VARCHAR(64),
                    surface VARCHAR(64),
                    event_type VARCHAR(128) NOT NULL,
                    detail JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_analyst_events_map_time "
                "ON analyst_events (map_id, received_at_ms)"))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_analyst_events_type_time "
                "ON analyst_events (event_type, received_at_ms)"))
    except Exception as e:
        logging.getLogger(__name__).warning("table bootstrap skipped: %s", e)
    # MCP session manager (mounted sub-app lifespans never run, so the
    # task group that serves /api/v1/mcp is driven from here). The
    # server instructions are rebuilt WITH the choice lists (registries,
    # template names, equipment names) now that the DB is bootstrapped —
    # drivers get them in their system context at connect, never via a
    # tool call.
    from app.mcp_server import mcp as _mcp, refresh_instructions
    from app.mcp_world import mcp as _world_mcp
    try:
        await refresh_instructions()
    except Exception as e:
        logging.getLogger(__name__).warning("mcp instruction lists skipped: %s", e)
    # Both MCP servers' streamable session managers run in this lifespan
    # (mounted sub-app lifespans never fire). The world-model ingestion server
    # (app/mcp_world.py) is the second surface.
    async with _mcp.session_manager.run():
        async with _world_mcp.session_manager.run():
            yield


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        # Skip noisy health checks
        if request.url.path == "/health":
            return response

        user_id = request.query_params.get("user_id", "-")
        logger.info(
            "%s %s %s user=%s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            user_id,
            duration_ms,
        )
        return response


app = FastAPI(
    title="Geo-Spatial Agent",
    description="AI-powered geo-spatial intelligence service",
    version="0.1.0",
    lifespan=lifespan,
)

class GeoApiAliasMiddleware:
    """Serve /geo-api/* natively by rewriting it to /api/* before routing.

    /geo-api is the prefix consumers' nginx exposes (rewriting to /api on
    the way in), and it is the DEFAULT base baked into this service's own
    frontend bundle (VITE_GEO_AGENT_API_URL falls back to /geo-api/v1).
    Without this alias, direct access to :9845 — the README quick start,
    a host with no consumer nginx, or the headless render target pointed
    at the backend itself — loads the SPA and then 404s every API, tile,
    and WebSocket call. Pure ASGI (not BaseHTTPMiddleware) so the rewrite
    also covers the websocket scope (/geo-api/v1/ws).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path") or ""
            # /geo-api/v1/mcp-sse is served by its OWN mount at the raw
            # external path (no rewrite): the SSE transport advertises
            # its message endpoint as root_path + "/messages/", and the
            # rewrite would make it advertise the INTERNAL /api/v1 path,
            # which external proxies route to the wrong service.
            if (path.startswith("/geo-api/")
                    and not path.startswith("/geo-api/v1/mcp-sse")
                    and not path.startswith("/geo-api/v1/world/mcp-sse")):
                new_path = "/api/" + path[len("/geo-api/"):]
                scope["path"] = new_path
                scope["raw_path"] = new_path.encode("latin-1")
        await self.app(scope, receive, send)


# Middleware (order matters: Starlette makes the LAST-added middleware
# the OUTERMOST — requests hit CORSRejectionLog first and the geo-api
# alias last, so the router always sees the rewritten /api path while
# the logging layers see the path the client actually sent).
app.add_middleware(GeoApiAliasMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX_STR,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    CORSRejectionLogMiddleware,
    allowed_origins=ALLOWED_ORIGINS,
    allowed_origin_regex=ALLOWED_ORIGIN_REGEX,
)

# Routes
app.include_router(api_router, prefix="/api/v1")

# MCP tool surface (extraction agent — build/verify/repair the entity
# graph). TWO transports over one server:
# - SSE at /api/v1/mcp-sse/sse (+ /messages/) — interactive Claude Code
#   sessions; auto-reconnects on drop, so every backend restart
#   propagates tool-schema changes without a manual /mcp reconnect.
#   Mounted FIRST: Starlette matches mounts in order and the /api/v1
#   mount below would otherwise swallow this more specific prefix.
# - Streamable HTTP at /api/v1/mcp — programmatic clients. Mounted at
#   /api/v1 with the sub-app serving /mcp so the canonical
#   no-trailing-slash URL matches without a 307 (which MCP clients do
#   not reliably follow on POST). Real /api/v1 routes are registered
#   above and always match first; only otherwise-404 paths reach it.
# Both are reachable via /geo-api/* through the alias middleware. The
# streamable session manager runs in this app's lifespan above.
from app.mcp_server import mcp_asgi_app, mcp_sse_app  # noqa: E402
from app.mcp_world import mcp_world_asgi_app, mcp_world_sse_app  # noqa: E402

# The external-path SSE mount serves /geo-api clients directly (the
# alias middleware exempts this prefix) so the advertised message
# endpoint carries the EXTERNAL prefix; the /api/v1 SSE mount serves
# direct :9845 access. Each mount has its own transport instance — a
# client's GET stream and POSTs stay on one mount.
app.mount("/geo-api/v1/mcp-sse", mcp_sse_app())
app.mount("/api/v1/mcp-sse", mcp_sse_app())
# SECOND MCP server — the world-model ingestion surface (app/mcp_world.py).
# Its world/mcp-sse mounts precede the /api/v1/world streamable mount, which
# precedes the catch-all /api/v1, so Starlette routes each to the right sub-app.
# Canonical paths: streamable /api/v1/world/mcp, SSE /api/v1/world/mcp-sse/sse.
app.mount("/geo-api/v1/world/mcp-sse", mcp_world_sse_app())
app.mount("/api/v1/world/mcp-sse", mcp_world_sse_app())
app.mount("/api/v1/world", mcp_world_asgi_app())
app.mount("/api/v1", mcp_asgi_app())


@app.get("/health")
async def health():
    return {"status": "healthy"}


# --- Frontend static-file mount --------------------------------------
# The geo-agent frontend (React + Vite build) is dropped into
# /srv/geo-agent by the multistage Dockerfile. Serve it under /geo-app/
# so nginx can proxy /geo-app/* → this container without a URL rewrite.
# In dev (no /srv/geo-agent), the mount is skipped so `uvicorn --reload`
# still boots against a bare backend checkout.
_FRONTEND_DIR = os.environ.get("GEO_AGENT_FRONTEND_DIR", "/srv/geo-agent")
if os.path.isdir(_FRONTEND_DIR):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    # SPA fallback — any /geo-app/... path that isn't a real file lands
    # on index.html so react-router owns client-side routing (/headless,
    # /operations-map).
    # index.html is served NO-STORE: it is the pointer to the hashed
    # bundles, and without an explicit cache header browsers cache it
    # heuristically — analysts kept running a STALE app for hours after
    # every deploy (fixes verified server-side were invisible in the
    # embedded iframe until a hard refresh). The hashed /assets/* stay
    # long-cached: their names change when their content does.
    _NO_STORE = {"Cache-Control": "no-store, must-revalidate"}

    def _index_response(directory):
        return FileResponse(
            os.path.join(directory, "index.html"), headers=_NO_STORE)

    class _SpaStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            # Starlette's StaticFiles either returns a 404 response OR
            # raises HTTPException(404) depending on version + config.
            # Handle both so client-side routes always resolve.
            try:
                resp = await super().get_response(path, scope)
                if resp.status_code == 404:
                    return _index_response(self.directory)
                if path in ("index.html", "", "."):
                    resp.headers.update(_NO_STORE)
                return resp
            except Exception:  # noqa: BLE001 — 404 signal from any Starlette
                return _index_response(self.directory)

    app.mount(
        "/geo-app",
        _SpaStaticFiles(directory=_FRONTEND_DIR, html=True),
        name="geo-agent-frontend",
    )
    logger.info("mounted geo-agent frontend at /geo-app (dir=%s)", _FRONTEND_DIR)
else:
    logger.info(
        "geo-agent frontend dir %s missing — /geo-app/ mount skipped "
        "(dev backend-only mode)", _FRONTEND_DIR,
    )

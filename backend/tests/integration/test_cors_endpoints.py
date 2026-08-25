"""Integration tests for CORS endpoint behavior.

These tests run against the actual geo-agent FastAPI application with
real middleware stack and routes.

Run with:
    ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173 \
    python -m pytest tests/integration/test_cors_endpoints.py -v
"""

import logging
import os
import re
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# Dev frontend origins — matches pytho-vite dev server ports
DEV_ORIGINS = "http://localhost:3000,http://localhost:5173"
# Production frontend origin
PROD_ORIGINS = "https://app.pytho.ai"
# Demo frontend origin
DEMO_ORIGINS = "https://beta.pytho.ai"


@pytest.fixture(scope="module")
def client():
    """Create a TestClient against the real geo-agent app with dev origins."""
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": DEV_ORIGINS}):
        from app.main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture(scope="module")
def prod_client():
    """Create a TestClient against the real geo-agent app with prod origins."""
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": PROD_ORIGINS}):
        from app.main import app
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# PRD Scenarios (1-5)
# ---------------------------------------------------------------------------

def test_cors_get_from_allowed_origin(client):
    """Allowed origin gets CORS headers on GET."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejected_origin(client):
    """Unknown origin gets no CORS headers."""
    response = client.get("/health", headers={"Origin": "http://evil.com"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_allowed(client):
    """Preflight from allowed origin returns CORS headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_rejected(client):
    """Preflight from rejected origin gets no CORS headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_no_origin_header_passes_through(client):
    """Server-to-server calls (no Origin header) work normally."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------------------
# Additional Scenarios (6-15)
# ---------------------------------------------------------------------------

def test_multiple_origins_correct_one_echoed(client):
    """Response echoes the requesting origin, not the first in the list."""
    r1 = client.get("/health", headers={"Origin": "http://localhost:3000"})
    r2 = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r1.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r2.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_post_json_preflight(client):
    """POST with Content-Type: application/json preflight passes."""
    preflight = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_preflight_with_authorization_header(client):
    """Preflight requesting Authorization header is allowed."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in allowed_headers or "*" in allowed_headers


def test_put_delete_preflight(client):
    """PUT and DELETE methods pass preflight for allowed origin."""
    for method in ["PUT", "DELETE"]:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": method,
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_origin_trailing_slash_not_matched(client):
    """Origin with trailing slash does NOT match."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000/"})
    assert "access-control-allow-origin" not in response.headers


def test_https_vs_http_different_origins(client):
    """https is a different origin than http."""
    response = client.get("/health", headers={"Origin": "https://localhost:3000"})
    assert "access-control-allow-origin" not in response.headers


def test_different_port_rejected(client):
    """Port not in allowlist is rejected."""
    response = client.get("/health", headers={"Origin": "http://localhost:5174"})
    assert "access-control-allow-origin" not in response.headers


def test_rejection_log_fires(client, caplog):
    """Rejected origin produces a WARNING log naming the exact origin.

    Asserts on the FULL origin URL, anchored, rather than a bare
    substring — a substring check would also pass on log lines about
    unrelated hosts that merely contain the fragment (and trips CodeQL
    py/incomplete-url-substring-sanitization).
    """
    rejected_origin = "http://attacker.com"
    with caplog.at_level(logging.WARNING):
        client.get("/health", headers={"Origin": rejected_origin})
    assert any(
        re.search(r"(^|[\s'\"])" + re.escape(rejected_origin) + r"($|[\s'\"/])",
                  record.message)
        for record in caplog.records
    )


def test_vary_origin_header_present(client):
    """Response includes Vary: Origin for correct caching."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    vary = response.headers.get("vary", "")
    assert "origin" in vary.lower()


def test_api_v1_routes_have_cors(client):
    """CORS applies to /api/v1/ prefixed routes too."""
    response = client.options(
        "/api/v1/entities",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ---------------------------------------------------------------------------
# Production environment scenarios (16-19)
# ---------------------------------------------------------------------------

def test_prod_origin_app_pytho_ai(prod_client):
    """Production frontend app.pytho.ai is allowed."""
    response = prod_client.get("/health", headers={"Origin": "https://app.pytho.ai"})
    assert response.headers.get("access-control-allow-origin") == "https://app.pytho.ai"


def test_prod_rejects_http_variant(prod_client):
    """http://app.pytho.ai (no TLS) is rejected in prod — only https allowed."""
    response = prod_client.get("/health", headers={"Origin": "http://app.pytho.ai"})
    assert "access-control-allow-origin" not in response.headers


def test_prod_rejects_localhost(prod_client):
    """localhost is rejected when running with prod origins."""
    response = prod_client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in response.headers


def test_prod_rejects_demo_origin(prod_client):
    """beta.pytho.ai is rejected on production — it's a separate deployment."""
    response = prod_client.get("/health", headers={"Origin": "https://beta.pytho.ai"})
    assert "access-control-allow-origin" not in response.headers

"""Unit tests for CORS origin parsing and middleware behavior.

Tests cover:
  1-5:  parse_allowed_origins() validation logic
  6-10: CORSMiddleware + CORSRejectionLogMiddleware HTTP behavior
"""

import os
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.cors import parse_allowed_origins, CORSRejectionLogMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(origins: list[str]) -> FastAPI:
    """Create a minimal FastAPI app with CORS middleware configured."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CORSRejectionLogMiddleware, allowed_origins=origins)

    @app.get("/api/test")
    def _test_endpoint():
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# 1-5: parse_allowed_origins() unit tests
# ---------------------------------------------------------------------------

def test_parse_allowed_origins_single():
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://localhost:3000"}):
        result = parse_allowed_origins()
    assert result == ["http://localhost:3000"]


def test_parse_allowed_origins_multiple():
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://localhost:3000,http://localhost:5173"}):
        result = parse_allowed_origins()
    assert result == ["http://localhost:3000", "http://localhost:5173"]


def test_parse_allowed_origins_whitespace():
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://localhost:3000 , http://localhost:5173"}):
        result = parse_allowed_origins()
    assert result == ["http://localhost:3000", "http://localhost:5173"]


def test_parse_allowed_origins_invalid_wildcard():
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "*"}):
        with pytest.raises(SystemExit):
            parse_allowed_origins()


def test_parse_allowed_origins_invalid_regex():
    with patch.dict(os.environ, {"ALLOWED_ORIGINS": "http://localhost:3000["}):
        with pytest.raises(SystemExit):
            parse_allowed_origins()


# ---------------------------------------------------------------------------
# 6-10: CORS middleware behavior tests
# ---------------------------------------------------------------------------

def test_cors_origin_allowed():
    client = TestClient(_make_app(["http://localhost:3000"]))
    response = client.get("/api/test", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_origin_rejected():
    client = TestClient(_make_app(["http://localhost:3000"]))
    response = client.get("/api/test", headers={"Origin": "http://evil.com"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_allowed():
    client = TestClient(_make_app(["http://localhost:3000"]))
    response = client.options(
        "/api/test",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_rejected():
    client = TestClient(_make_app(["http://localhost:3000"]))
    response = client.options(
        "/api/test",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_missing_origin_header():
    client = TestClient(_make_app(["http://localhost:3000"]))
    response = client.get("/api/test")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "access-control-allow-origin" not in response.headers

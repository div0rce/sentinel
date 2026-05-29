"""Tests for the M10 request-id middleware."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.db import get_session
from backend.app.main import app
from backend.app.observability import REQUEST_ID_HEADER

UUID_HEX = re.compile(r"^[a-f0-9]{32}$")


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert REQUEST_ID_HEADER in resp.headers
    request_id = resp.headers[REQUEST_ID_HEADER]
    assert UUID_HEX.match(request_id), f"unexpected request id format: {request_id!r}"


def test_inbound_request_id_is_echoed_when_safe(client: TestClient) -> None:
    inbound = "client-supplied-abc123"
    resp = client.get("/health", headers={REQUEST_ID_HEADER: inbound})
    assert resp.headers[REQUEST_ID_HEADER] == inbound


@pytest.mark.parametrize(
    "rogue",
    [
        "x" * 128,  # too long
        "spaces here",  # space disallowed
        "newline\nhere",  # control char
        ";rm -rf /",  # punctuation outside [-_]
        "",  # empty
    ],
)
def test_unsafe_inbound_request_ids_are_replaced(client: TestClient, rogue: str) -> None:
    resp = client.get("/health", headers={REQUEST_ID_HEADER: rogue})
    out = resp.headers[REQUEST_ID_HEADER]
    assert out != rogue
    # The replacement is the generated UUID hex form.
    assert UUID_HEX.match(out), f"replacement did not look generated: {out!r}"


def test_each_request_gets_a_distinct_generated_id(client: TestClient) -> None:
    a = client.get("/health").headers[REQUEST_ID_HEADER]
    b = client.get("/health").headers[REQUEST_ID_HEADER]
    assert a != b

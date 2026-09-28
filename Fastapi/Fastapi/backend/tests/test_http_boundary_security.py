"""Regression tests for the loopback HTTP security boundary."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify.api.app import app


client = TestClient(app)


def test_foreign_host_is_refused():
    response = client.get("/healthz", headers={"Host": "attacker.example"})
    assert response.status_code == 400


def test_loopback_hosts_are_accepted():
    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "testserver"):
        response = client.get("/healthz", headers={"Host": host})
        assert response.status_code == 200


def test_cross_site_and_null_origin_writes_are_refused():
    for origin in ("https://evil.example", "null"):
        response = client.post("/api/v0/demo/cart/reset", headers={"Origin": origin})
        assert response.status_code == 403


def test_same_origin_and_originless_writes_still_work():
    same = client.post("/api/v0/demo/cart/reset", headers={"Origin": "http://testserver"})
    assert same.status_code == 200
    assert client.post("/api/v0/demo/cart/reset").status_code == 200


def test_reads_are_not_blocked_by_origin_header():
    response = client.get("/api/v0/cart", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200


def test_http_refuses_deterministic_parity_mode_but_engine_remains_available():
    with patch.dict(os.environ, {"RAMIFY_DEMO_DETERMINISTIC": "1"}):
        assert client.get("/healthz").status_code == 503

        # The guard is HTTP-only; deterministic direct-engine parity remains usable.
        from ramify import engine
        first = engine.assess("ramify:demo:supp:apex-mg-glyc-120", persist_receipt=False)["receipt"]["payload_hash"]
        second = engine.assess("ramify:demo:supp:apex-mg-glyc-120", persist_receipt=False)["receipt"]["payload_hash"]
        assert first == second

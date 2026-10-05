"""Optional browser-level smoke tests for David's final-evidence request.

These tests use a real Chromium browser when Playwright and a system browser are
available. They deliberately skip in minimal CI/student environments rather than
making the ordinary backend suite depend on a browser install.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = next((Path(p) for p in ("/usr/bin/chromium", "/usr/bin/chromium-browser") if Path(p).exists()), None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _server(*, enable_agent: bool = False):
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Playwright is not installed: {exc}")

    port = _free_port()
    with tempfile.TemporaryDirectory() as store:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend")
        env["RAMIFY_DATA_DIR"] = store
        if enable_agent:
            env.pop("RAMIFY_DISABLE_AGENT", None)
        else:
            env["RAMIFY_DISABLE_AGENT"] = "1"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "ramify.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            import urllib.request
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.25) as response:
                        if response.status == 200:
                            break
                except Exception:
                    if proc.poll() is not None:
                        out, err = proc.communicate(timeout=1)
                        pytest.fail(f"Uvicorn exited early\nSTDOUT:\n{out}\nSTDERR:\n{err}")
                    time.sleep(0.1)
            else:
                pytest.fail("Uvicorn did not become ready")
            yield f"http://127.0.0.1:{port}"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def _browser_page(base_url: str):
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = None
    try:
        launch_options = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-web-security",
                "--no-proxy-server",
                "--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights",
            ],
        }
        if CHROMIUM is not None:
            launch_options["executable_path"] = str(CHROMIUM)

        browser = pw.chromium.launch(**launch_options)

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(base_url + "/shop", wait_until="domcontentloaded")
        return pw, browser, page
    except Exception as exc:  # Chromium can be blocked by host policy in locked-down runners.
        if browser is not None:
            browser.close()
        pw.stop()
        pytest.skip(f"Chromium could not open the local demo: {exc}")


@pytest.mark.browser_e2e
def test_browser_consumer_can_complete_authorised_checkout():
    with _server() as base_url:
        pw, browser, page = _browser_page(base_url)
        try:
            assert "RAMIFY" in page.title()
            result = page.evaluate(
                """async () => {
                    const assess = await fetch('/api/v0/assess', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({identifier:'ramify:demo:supp:apex-mg-glyc-120', actor_ref:'consumer_v1', quantity:1, context:'purchase'})
                    }).then(r => r.json());
                    const add = await fetch('/api/v0/cart/add', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({receipt_ref: assess.receipt_ref})
                    }).then(r => r.json());
                    const checkout = await fetch('/api/v0/cart/checkout', {method: 'POST'}).then(r => r.json());
                    const verify = await fetch('/api/v0/receipt/verify', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify(checkout.order)
                    }).then(r => r.json());
                    return {assess, add, checkout, verify};
                }"""
            )
            assert result["assess"]["actor_decision"] == "allow"
            assert result["add"]["line"]["receipt_ref"] == result["assess"]["receipt_ref"]
            assert result["checkout"]["order"]["record_type"] == "order_record"
            assert result["verify"]["integrity_verified"] is True
        finally:
            browser.close()
            pw.stop()


@pytest.mark.browser_e2e
def test_browser_human_successor_can_authorise_procurement_requisition():
    with _server() as base_url:
        pw, browser, page = _browser_page(base_url)
        try:
            result = page.evaluate(
                """async () => {
                    const assess = await fetch('/api/v0/assess', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({identifier:'ramify:demo:supp:northbeam-vitc-1000-b2025-03-A', actor_ref:'procurement_v1', quantity:1, context:'purchase'})
                    }).then(r => r.json());
                    const review = await fetch('/api/v0/receipt/review', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({receipt_id: assess.receipt_ref, outcome:'overridden', reviewer_name:'Browser reviewer', reviewer_role:'Procurement approver'})
                    }).then(r => r.json());
                    const action = await fetch('/api/v0/action', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({receipt_ref: review.receipt_ref, action:'create_mock_requisition'})
                    }).then(r => r.json());
                    const req = await fetch('/api/v0/requisition/create', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({receipt_ref: review.receipt_ref})
                    }).then(r => r.json());
                    const verify = await fetch('/api/v0/receipt/verify', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify(req.requisition)
                    }).then(r => r.json());
                    return {assess, review, action, req, verify};
                }"""
            )
            assert result["assess"]["requires_human"] is True
            assert result["review"]["supersedes"] == result["assess"]["receipt_ref"]
            assert result["action"]["event"]["action"] == "create_mock_requisition"
            assert result["req"]["requisition"]["record_type"] == "requisition_record"
            assert result["verify"]["integrity_verified"] is True
        finally:
            browser.close()
            pw.stop()


@pytest.mark.browser_e2e
def test_browser_recall_cannot_be_softened_or_routed_around():
    with _server() as base_url:
        pw, browser, page = _browser_page(base_url)
        try:
            result = page.evaluate(
                """async () => {
                    const identifier = 'ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K';

                    const compare = await fetch('/api/v0/compare', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({identifier, quantity:1})
                    }).then(r => r.json());

                    const assess = await fetch('/api/v0/assess', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({
                        identifier,
                        actor_ref:'consumer_v1',
                        quantity:1,
                        context:'purchase'
                      })
                    }).then(r => r.json());

                    const alternatives = await fetch('/api/v0/alternatives', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({
                        identifier,
                        actor_ref:'consumer_v1',
                        quantity:1
                      })
                    }).then(r => r.json());

                    const cartResponse = await fetch('/api/v0/cart/add', {
                      method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({receipt_ref: assess.receipt_ref})
                    });

                    return {
                      compare,
                      assess,
                      alternatives,
                      cart_status: cartResponse.status
                    };
                }"""
            )

            assert result["compare"]["objective_posture"] == "block"
            assert all(
                persona["decision"] == "block"
                for persona in result["compare"]["personas"]
            )
            assert result["assess"]["permitted_actions"] == ["halt"]
            assert result["assess"]["can_add_to_cart"] is False
            assert result["alternatives"]["alternatives"] is None
            assert result["cart_status"] == 409
        finally:
            browser.close()
            pw.stop()


@pytest.mark.browser_e2e
def test_browser_free_text_uses_deterministic_fallback_without_local_model():
    with _server() as base_url:
        pw, browser, page = _browser_page(base_url)
        try:
            result = page.evaluate(
                """async () => {
                    const status = await fetch('/api/v0/agent/status')
                        .then(r => r.json());

                    const interpretation = await fetch('/api/v0/interpret', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            request_text: 'I want Apex magnesium glycinate',
                            actor_ref: 'consumer_v1',
                            mode: 'auto'
                        })
                    }).then(r => r.json());

                    return {status, interpretation};
                }"""
            )

            assert result["status"]["active_mode"] == "deterministic_fallback"
            assert result["status"]["fallback_available"] is True
            assert (
                result["interpretation"]["identifier"]
                == "ramify:demo:supp:apex-mg-glyc-120"
            )
            assert result["interpretation"]["actor_ref"] == "consumer_v1"
            assert result["interpretation"]["authoritative"] is False
            assert "deterministic engine decides trust" in result["interpretation"]["boundary"]
        finally:
            browser.close()
            pw.stop()

@pytest.mark.browser_e2e
@pytest.mark.skipif(
    os.environ.get("RAMIFY_TEST_LIVE_MODEL") != "1",
    reason="set RAMIFY_TEST_LIVE_MODEL=1 with Ollama and a local model running",
)
def test_browser_free_text_uses_local_model_without_decision_authority():
    with _server(enable_agent=True) as base_url:
        pw, browser, page = _browser_page(base_url)
        try:
            result = page.evaluate(
                """async () => {
                    const status = await fetch('/api/v0/agent/status')
                        .then(r => r.json());

                    const interpretation = await fetch('/api/v0/interpret', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            request_text: 'nitrite examination gloves medium',
                            actor_ref: 'consumer_v1',
                            mode: 'auto'
                        })
                    }).then(r => r.json());

                    return {status, interpretation};
                }"""
            )

            assert result["status"]["active_mode"] == "local_llm"
            assert result["status"]["local_model_available"] is True
            assert result["interpretation"]["authoritative"] is False
            assert "deterministic engine decides trust" in result["interpretation"]["boundary"]
        finally:
            browser.close()
            pw.stop()

"""Optional real-browser acceptance journeys.

These tests intentionally exercise visible controls for the core client journeys.
They skip only when browser infrastructure is unavailable. Live-model coverage
is separate opt-in evidence and its skip is never treated as proof of inference.
"""
from __future__ import annotations
import os, socket, subprocess, sys, tempfile, time
from contextlib import contextmanager
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = next((Path(p) for p in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome") if Path(p).exists()), None)
APEX = "ramify:demo:supp:apex-mg-glyc-120"
NORTHBEAM = "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A"
RECALL = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"

def _free_port():
    with socket.socket() as s: s.bind(("127.0.0.1",0)); return int(s.getsockname()[1])

@contextmanager
def _server(*, enable_agent=False):
    if CHROMIUM is None: pytest.skip("Chromium is not installed")
    try: from playwright.sync_api import sync_playwright  # noqa
    except Exception as exc: pytest.skip(f"Playwright is not installed: {exc}")
    port=_free_port()
    with tempfile.TemporaryDirectory() as store:
        env=os.environ.copy(); env["PYTHONPATH"]=str(ROOT/"backend"); env["RAMIFY_DATA_DIR"]=store
        if enable_agent: env.pop("RAMIFY_DISABLE_AGENT",None)
        else: env["RAMIFY_DISABLE_AGENT"]="1"
        proc=subprocess.Popen([sys.executable,"-m","uvicorn","ramify.api.app:app","--host","127.0.0.1","--port",str(port),"--log-level","warning"],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            import urllib.request
            for _ in range(80):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",timeout=.25) as response:
                        if response.status==200: break
                except Exception:
                    if proc.poll() is not None:
                        out,err=proc.communicate(timeout=1); pytest.fail(f"Uvicorn exited early\nSTDOUT:\n{out}\nSTDERR:\n{err}")
                    time.sleep(.1)
            else: pytest.fail("Uvicorn did not become ready")
            yield f"http://127.0.0.1:{port}"
        finally:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)

def _browser_page(base_url):
    from playwright.sync_api import sync_playwright
    pw=sync_playwright().start(); browser=None
    try:
        kwargs={"headless":True,"args":["--no-sandbox","--disable-web-security","--no-proxy-server","--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights"]}
        if CHROMIUM: kwargs["executable_path"]=str(CHROMIUM)
        browser=pw.chromium.launch(**kwargs)
        page=browser.new_page(viewport={"width":1440,"height":1000}); page.goto(base_url+"/shop",wait_until="domcontentloaded")
        if page.locator("#welcome-close").count() and page.locator("#welcome-close").is_visible(): page.locator("#welcome-close").click()
        return pw,browser,page
    except Exception as exc:
        if browser: browser.close()
        pw.stop(); pytest.skip(f"Chromium could not open the local demo: {exc}")

def _select_and_run(page, subject_ref, actor_ref="consumer_v1"):
    page.locator("#actor").select_option(actor_ref)
    page.locator(f'.card[data-ref="{subject_ref}"]').click()
    page.locator("#selection-panel").wait_for(state="visible")
    page.locator("#continue-ramify").click(); page.locator("#result").wait_for(state="visible",timeout=15000)

def _advance_to_checkout_stage(page):
    for _ in range(4): page.locator("#journey-next").click()
    page.locator('[data-stage="5"]').wait_for(state="visible")

@pytest.mark.browser_e2e
def test_browser_consumer_can_complete_authorised_checkout_through_visible_ui():
    with _server() as base_url:
        pw,browser,page=_browser_page(base_url)
        try:
            _select_and_run(page,APEX); _advance_to_checkout_stage(page); page.locator("#add-to-cart").click(); page.wait_for_url("**/cart",timeout=10000)
            page.locator("#checkout").click(); page.get_by_text("Order placed",exact=False).wait_for(state="visible",timeout=10000); assert page.locator(".order-record").count()>=1
        finally: browser.close(); pw.stop()

@pytest.mark.browser_e2e
def test_browser_procurement_human_review_creates_requisition_through_visible_ui():
    with _server() as base_url:
        pw,browser,page=_browser_page(base_url)
        try:
            _select_and_run(page,NORTHBEAM,"procurement_v1"); _advance_to_checkout_stage(page); page.get_by_text("Open human review",exact=False).click(); page.wait_for_url("**/review",timeout=10000)
            page.locator('[data-decide="overridden"]').first.click(); page.wait_for_timeout(900); page.goto(base_url+"/cart",wait_until="domcontentloaded")
            page.get_by_text("Procurement requisitions",exact=False).wait_for(state="visible",timeout=10000); assert page.locator('[data-verify-requisition]').count()>=1
        finally: browser.close(); pw.stop()

@pytest.mark.browser_e2e
def test_browser_recall_cannot_be_softened_or_routed_around():
    with _server() as base_url:
        pw,browser,page=_browser_page(base_url)
        try:
            _select_and_run(page,RECALL); _advance_to_checkout_stage(page); page.get_by_text("Checkout is blocked",exact=False).wait_for(state="visible"); assert page.locator("#add-to-cart").count()==0
        finally: browser.close(); pw.stop()

@pytest.mark.browser_e2e
def test_browser_free_text_uses_deterministic_fallback_without_local_model():
    with _server() as base_url:
        pw,browser,page=_browser_page(base_url)
        try:
            page.locator("#query").fill("I want Apex magnesium glycinate"); page.locator("#run").click(); page.locator("#result").wait_for(state="visible",timeout=15000); page.locator("#ai-fallback-banner").wait_for(state="visible"); assert page.get_by_text("safe catalogue matcher",exact=False).count()>=1
        finally: browser.close(); pw.stop()

@pytest.mark.browser_e2e
@pytest.mark.skipif(os.environ.get("RAMIFY_TEST_LIVE_MODEL")!="1",reason="set RAMIFY_TEST_LIVE_MODEL=1 with Ollama and a local model running")
def test_browser_free_text_uses_local_model_without_decision_authority():
    with _server(enable_agent=True) as base_url:
        pw,browser,page=_browser_page(base_url)
        try:
            page.locator("#query").fill("nitrite examination gloves medium"); page.locator("#run").click(); page.locator("#result").wait_for(state="visible",timeout=45000); page.get_by_text("Understood with local AI",exact=False).wait_for(state="visible",timeout=45000)
            assert page.get_by_text("Product trust is created by the deterministic RAMIFY checks",exact=False).count()>=1
        finally: browser.close(); pw.stop()

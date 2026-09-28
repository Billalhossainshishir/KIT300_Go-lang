from pathlib import Path

from fastapi.testclient import TestClient

from ramify.api.app import app

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def test_interactive_tour_page_and_asset_are_served():
    client = TestClient(app)
    page = client.get("/tour")
    script = client.get("/tour.js")
    assert page.status_code == 200
    assert "Interactive tour" in page.text
    assert script.status_code == 200
    assert "TOUR_STEPS" in script.text


def test_shop_opens_first_run_choice_and_overview_is_removed():
    html = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
    assert "mountFirstRunWelcome()" in html
    assert not (FRONTEND / "pages" / "overview.html").exists()


def test_first_run_choice_has_both_requested_paths():
    js = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
    assert "Explore the demo myself" in js
    assert "Guide me through the full tour" in js
    assert 'window.location.href = "/shop"' in js
    assert 'window.location.href = "/tour"' in js


def test_tour_returns_to_shop_and_help_can_restart_it():
    js = (FRONTEND / "scripts" / "tour.js").read_text(encoding="utf-8")
    help_html = (FRONTEND / "pages" / "help.html").read_text(encoding="utf-8")
    assert 'window.location.href = "/shop"' in js
    assert "ramify-tour-complete" not in js
    assert 'href="/tour"' in help_html


def test_needs_me_has_no_reviewer_form_and_shop_marks_purchase_context():
    review_html = (FRONTEND / "pages" / "review.html").read_text(encoding="utf-8")
    review_js = (FRONTEND / "scripts" / "review.js").read_text(encoding="utf-8")
    shop_js = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
    assert "Who is reviewing this?" not in review_html
    assert 'id="reviewer-name"' not in review_html
    assert 'id="reviewer-role"' not in review_html
    assert '$("reviewer-name")' not in review_js
    assert 'context: "purchase"' in shop_js

def test_rebuilt_tour_uses_one_clear_primary_action_and_real_catalogue_product():
    js = (FRONTEND / "scripts" / "tour.js").read_text(encoding="utf-8")
    page = (FRONTEND / "pages" / "tour.html").read_text(encoding="utf-8")
    css = (FRONTEND / "styles" / "style.css").read_text(encoding="utf-8")
    assert 'GUIDED_PRODUCT_REF = "ramify:demo:supp:apex-mg-glyc-120"' in js
    assert 'id="walkthrough-primary"' in page
    assert 'id="walkthrough-back"' in page
    assert '.walkthrough-product-image img' in css
    assert 'object-fit:contain' in css
    assert '/tour.js?v=11.0.7-uxfix-rebuild' in page


def test_guided_flows_do_not_wait_for_live_llm():
    root = Path(__file__).resolve().parents[2]
    tour_js = (root / "frontend" / "scripts" / "tour.js").read_text(encoding="utf-8")
    demo_js = (root / "frontend" / "scripts" / "demo.js").read_text(encoding="utf-8")
    assert 'mode: "deterministic"' in tour_js
    assert 'mode: "deterministic"' in demo_js
    shop_js = (root / "frontend" / "scripts" / "console.js").read_text(encoding="utf-8")
    assert 'candidateRefs?.length === 1 ? "deterministic" : "auto"' in shop_js
    assert 'mode: interpretationMode' in shop_js


def test_tour_keeps_exploration_separate_from_purchase_authority():
    js = (FRONTEND / "scripts" / "tour.js").read_text(encoding="utf-8")
    assert 'context: "interactive_tour"' in js
    assert '/api/v0/cart/add' not in js
    assert 'The guided tour does not create purchase authority.' in js
    assert 'Shop → Amplify' in js


def test_tour_has_six_linear_stages_and_does_not_require_repeat_clicks_to_reveal():
    js = (FRONTEND / "scripts" / "tour.js").read_text(encoding="utf-8")
    for key in ['key: "product"', 'key: "request"', 'key: "ramify"', 'key: "agent"', 'key: "receipt"', 'key: "finish"']:
        assert key in js
    assert 'runPrimaryAction' in js
    assert 'goToStep(2)' in js
    assert 'goToStep(3)' in js
    assert 'goToStep(5)' in js


def test_tour_shows_objective_result_separately_from_agent_policy():
    js = (FRONTEND / "scripts" / "tour.js").read_text(encoding="utf-8")
    assert 'OBJECTIVE PRODUCT RESULT' in js
    assert 'Objective trust' in js
    assert 'Consumer agent decision' in js
    assert 'Every agent sees the same objective product result.' in js


def test_tour_preserves_popup_implementation_and_only_rebuilds_post_popup_page():
    shell = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
    assert 'Guide me through the full tour' in shell
    assert 'window.location.href = "/tour"' in shell
    page = (FRONTEND / "pages" / "tour.html").read_text(encoding="utf-8")
    assert 'One product. Six clear steps. One auditable decision.' in page

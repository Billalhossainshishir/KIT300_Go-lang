from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_shop_uses_curated_story_library_without_scenario_lab_or_manual_ai_mode():
    page = read("pages/console.html")
    js = read("scripts/console.js")
    assert 'scenario-lab' not in page
    assert 'id="scenario-featured"' in page
    assert 'id="story-filter-bar"' in page
    assert 'Choose the story you want to demonstrate' in page
    assert 'id="no-ai-mode"' not in page
    assert "Run without AI" not in page
    for label in ["Approved", "Expired evidence", "Seller risk", "Recall", "Substitution"]:
        assert label in js
    assert 'candidateRefs?.length === 1 ? "deterministic" : "auto"' in js
    assert '$("no-ai-mode")' not in js


def test_primary_journey_progress_replaces_duplicate_trust_timeline():
    page = read("pages/console.html")
    js = read("scripts/console.js")
    assert 'id="journey-progress"' in page
    assert 'id="trust-timeline"' not in page
    assert "Request · 2/6" in page
    assert 'id="session-summary"' in page
    assert "SESSION SUMMARY" in js


def test_each_product_exposes_a_trust_passport_without_assessing():
    js = read("scripts/console.js")
    shell = read("scripts/shell.js")
    assert "Trust passport" in js
    assert "openTrustPassport" in js
    assert "PRODUCT TRUST PASSPORT" in shell
    assert "browsing this passport creates no purchase authority" in shell


def test_result_explains_why_and_shows_risk_path():
    page = read("pages/console.html")
    js = read("scripts/console.js")
    assert 'id="risk-path"' in page
    assert "No persona can override a hard stop" in js
    assert 'id="why-panel"' in page
    assert "Why this result?" in js


def test_live_evidence_trail_uses_backend_source_records():
    js = read("scripts/console.js")
    assert "LIVE SOURCE EVIDENCE" in js
    assert "/api/v0/subject/" in js
    assert "View source evidence" in js


def test_receipt_story_has_summary_evidence_json_export_and_tamper_demo():
    js = read("scripts/console.js")
    for label in ["Summary", "Evidence trail", "Signed JSON", "Export JSON", "Tamper demo"]:
        assert label in js
    assert "downloadCurrentReceipt" in js
    assert "tamperTest" in js


def test_personas_have_policy_fingerprints_and_fixed_truth_message():
    page = read("pages/agents.html")
    js = read("scripts/agents.js")
    shell = read("scripts/shell.js")
    assert "ONE PRODUCT TRUTH" in page
    assert "personaFingerprint" in js
    assert "Policy fingerprint" in shell


def test_ai_boundary_is_visible_and_about_has_before_after_story():
    technical = read("pages/technical.html")
    about = read("pages/about.html")
    assert "OUTSIDE THE TRUST BOUNDARY" in technical
    assert "TRUSTED RAMIFY CORE" in technical
    assert "Before RAMIFY / after RAMIFY" in about
    assert "Built from client feedback" in about


def test_human_review_and_activity_tell_a_four_part_audit_story():
    review = read("pages/review.html")
    activity = read("pages/activity.html")
    activity_js = read("scripts/activity.js")
    for text in ["RAMIFY found", "Agent wanted", "Human decides", "New receipt"]:
        assert text in review
    for text in ["What happened", "Who decided", "Why", "Proof"]:
        assert text in activity or text in activity_js


def test_start_fresh_preserves_audit_history():
    page = read("pages/console.html")
    js = read("scripts/console.js")
    assert 'id="start-fresh"' in page
    assert "Existing receipts and audit history were not deleted" in js
    assert "/api/v0/cart" not in js[js.index("function startFresh"): js.index("function renderTrustTimeline")]
    assert 'if (event.target.closest("[data-inspect]")) return;' in js
    checkout = js[js.index('const restart = $("checkout-restart")'): js.index('function renderInterpretation')]
    assert 'clearPreparedProduct({ keepQuery: false, preserveActor: true })' in checkout
    helper = js[js.index('function clearPreparedProduct'): js.index('function handleRequestEdit')]
    assert 'selectedProductRef = null' in helper
    assert 'selectedRequestText = ""' in helper
    assert '$("query").value = ""' in helper
    assert 'classList.remove("selected")' in helper
    assert "Existing receipts and audit history were not changed" in checkout


def test_sound_feature_is_removed_and_reduced_motion_is_supported():
    shell = read("scripts/shell.js")
    css = read("styles/style.css")
    assert "Sound on" not in shell
    assert "Sound off" not in shell
    assert "RAMIFY_SOUND_KEY" not in shell
    assert "ramify-sound-toggle" not in shell
    assert "AudioContext" not in shell
    assert ".sound-toggle" not in css
    assert "prefers-reduced-motion" in css



def test_consistent_vocabulary_is_explained_in_help():
    help_page = read("pages/help.html")
    for phrase in ["Product truth", "Agent policy", "Permitted action", "Human review", "Signed receipt"]:
        assert phrase in help_page

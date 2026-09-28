from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
STYLE = (FRONTEND / "styles" / "style.css").read_text(encoding="utf-8")
SHELL = (FRONTEND / "scripts" / "shell.js").read_text(encoding="utf-8")
CONSOLE = (FRONTEND / "scripts" / "console.js").read_text(encoding="utf-8")
HUMAN = (FRONTEND / "scripts" / "human-receipt.js").read_text(encoding="utf-8")


def test_non_shop_headers_are_compact_and_shop_hero_is_preserved():
    assert ".page-head:not(.shop-head)" in STYLE
    assert ".shop-head {" in STYLE


def test_button_hover_and_focus_keep_explicit_readable_colours():
    assert ".btn:hover" in STYLE
    assert ".btn:focus-visible" in STYLE
    assert ".btn-ghost:hover" in STYLE
    assert ".btn-quiet:hover" in STYLE


def test_agent_decision_scan_artifact_is_removed():
    assert ".light::after { display:none !important; }" in STYLE


def test_basket_and_human_actions_wrap_instead_of_overlapping():
    assert ".queue-actions" in STYLE
    assert "flex-wrap:wrap !important" in STYLE
    assert ".cart-line .cright" in STYLE


def test_receipt_statuses_are_presented_separately():
    assert "Receipt integrity" in CONSOLE
    assert "Evidence validity" in CONSOLE
    assert "Permitted action" in CONSOLE
    assert "Purchase authority" in CONSOLE
    assert "receipt-status-grid" in CONSOLE


def test_human_receipt_has_plain_status_summary_before_json():
    assert "Human outcome" in HUMAN
    assert "Transaction authority" in HUMAN
    assert "data-human-status" in HUMAN


def test_product_images_are_forced_to_contain():
    assert "object-fit:contain !important" in STYLE


def test_human_receipts_has_direct_navigation_entry():
    assert '["/human-receipt", "Human receipts"' in SHELL


def test_stale_decision_output_is_cleared_when_product_or_request_changes():
    assert "function clearDecisionOutput()" in CONSOLE
    assert "clearDecisionOutput();" in CONSOLE
    assert 'alternatives.innerHTML = ""' in CONSOLE
    assert 'terminal.textContent = ""' in CONSOLE


def test_forbidden_removed_ui_features_are_not_reintroduced():
    combined = "\n".join(
        p.read_text(encoding="utf-8")
        for p in FRONTEND.rglob("*")
        if p.is_file() and p.suffix in {".html", ".js"}
    )
    assert "Scenario Lab" not in combined
    assert "Presentation Mode" not in combined
    assert "sound toggle" not in combined.lower()
    assert "ai mode toggle" not in combined.lower()


def test_frontend_pages_reference_uxfix_assets():
    pages = list((FRONTEND / "pages").glob("*.html"))
    assert pages
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for src in ("/style.css", "/shell.js"):
            if src in text:
                assert "uxfix" in text

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestFrontendRuntimeGuards(unittest.TestCase):
    def test_shop_alternatives_renderer_is_defined_and_isolated(self):
        js = (ROOT / "frontend" / "scripts" / "console.js").read_text(encoding="utf-8")
        self.assertIn("void renderAlternatives(result);", js)
        self.assertIn("async function renderAlternatives(result)", js)
        self.assertIn("response?.alternatives", js)
        self.assertIn("Alternatives are temporarily unavailable", js)

    def test_current_ux_regression_markers(self):
        html = (ROOT / "frontend" / "pages" / "console.html").read_text(encoding="utf-8")
        console_js = (ROOT / "frontend" / "scripts" / "console.js").read_text(encoding="utf-8")
        shell_js = (ROOT / "frontend" / "scripts" / "shell.js").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "styles" / "style.css").read_text(encoding="utf-8")

        for forbidden in (
            'id="trust-timeline"',
            "new MutationObserver(",
            "new IntersectionObserver(",
            'dot.className = "ui-ripple"',
        ):
            self.assertNotIn(forbidden, html + "\n" + shell_js)

        required = (
            ("empty request validation", console_js, "Enter a product name or select a product first."),
            ("start fresh confirmation", console_js, "Start a fresh journey?"),
            ("request busy state", console_js, 'setAttribute("aria-busy", "true")'),
            ("story keyboard focus trap", console_js, "drawer._focusTrap"),
            ("agent-step badge timing", console_js, "if (journeyStep >= 3) void refreshBadges();"),
            ("demo story explanation", html, "Demo stories are prepared examples"),
            ("compact journey navigation", html, "Request · 2/6"),
            ("trust passport close control", shell_js, 'id="trust-passport-x"'),
            ("toast live feedback", shell_js, "aria-live"),
            ("agent policy handoff", shell_js, "Agent policy handoff"),
            ("guided readability audit", css, "Final project-wide readability/performance audit"),
            ("story drawer viewport safety", css, "max-height:calc(100dvh - 24px)"),
            ("product hover stability", css, ".journey-main .card::before"),
        )
        for name, source, marker in required:
            with self.subTest(name=name):
                self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()

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

if __name__ == "__main__":
    unittest.main()

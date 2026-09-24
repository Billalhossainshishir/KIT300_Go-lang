"""The decision path imports no agent framework.

Deliverable 2 claims that no language model participates in a trust decision.
This test turns that claim into a property of the code. It parses every module
in the decision path and fails if any of them imports an agent framework or the
adapter package, so the claim can be checked by a third party rather than taken
on trust.

It is also what makes component 6 replaceable. If a LangGraph adapter can be
swapped for a PydanticAI one without touching components 1 to 5, that is
because nothing in components 1 to 5 knows either exists.
"""

import ast
import os
import unittest
from pathlib import Path
from unittest import mock

import ramify

PACKAGE_ROOT = Path(ramify.__file__).resolve().parent

# Components 1 to 5 plus the shared crypto layer and the composition root.
DECISION_PATH = (
    "data",
    "crypto",
    "resolve",
    "ratify",
    "policy",
    "receipt",
    "action",
)

FRAMEWORK_MARKERS = (
    "langgraph",
    "langchain",
    "pydantic_ai",
    "crewai",
    "google.adk",
    "agent_framework",
    "openai",
    "anthropic",
    "ollama",
    "transformers",
    "llama_cpp",
)


def modules_in_decision_path() -> list[Path]:
    paths = [PACKAGE_ROOT / "engine.py", PACKAGE_ROOT / "timing.py"]
    for package in DECISION_PATH:
        paths.extend(sorted((PACKAGE_ROOT / package).rglob("*.py")))
    return paths


def imported_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


class TestImportBoundary(unittest.TestCase):
    def test_decision_path_imports_no_agent_framework(self):
        for path in modules_in_decision_path():
            with self.subTest(module=path.relative_to(PACKAGE_ROOT).as_posix()):
                for name in imported_names(path):
                    for marker in FRAMEWORK_MARKERS:
                        self.assertNotIn(
                            marker,
                            name.lower(),
                            f"{path.name} imports {name}, which puts a model in the "
                            "decision path",
                        )

    def test_decision_path_does_not_import_the_adapter_package(self):
        for path in modules_in_decision_path():
            with self.subTest(module=path.relative_to(PACKAGE_ROOT).as_posix()):
                for name in imported_names(path):
                    self.assertFalse(
                        name.startswith("ramify.agent"),
                        f"{path.name} imports {name}",
                    )

    def test_the_boundary_covers_every_module_it_should(self):
        # A new package added to the decision path without being listed here
        # would silently escape the check.
        packages = {
            child.name
            for child in PACKAGE_ROOT.iterdir()
            if child.is_dir() and (child / "__init__.py").exists()
        }
        unchecked = packages - set(DECISION_PATH) - {"agent", "api"}
        self.assertEqual(unchecked, set(), f"unchecked packages: {unchecked}")

    def test_the_protocol_module_itself_imports_no_framework(self):
        # The adapter interface is the seam. If it reached for a framework,
        # every adapter would inherit that dependency.
        for name in imported_names(PACKAGE_ROOT / "agent" / "protocol.py"):
            for marker in FRAMEWORK_MARKERS:
                self.assertNotIn(marker, name.lower())


@mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "1"})
class TestExplanationCannotAlterTheReceipt(unittest.TestCase):
    def test_the_model_receives_a_copy(self):
        from ramify.agent import explain
        from ramify.engine import assess

        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        before = dict(receipt)
        explain.explain_receipt(receipt)
        self.assertEqual(receipt, before, "explanation mutated the receipt it was given")

    def test_an_explanation_is_always_produced(self):
        # With no model configured the deterministic summary stands in, so a
        # slow or absent local model cannot break the demonstration.
        from ramify.agent import explain
        from ramify.engine import assess

        result = explain.explain_receipt(assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"])
        self.assertTrue(result["text"].strip())
        self.assertIn("source", result)

    def test_explanation_of_a_blocked_receipt_says_so(self):
        from ramify.agent import explain
        from ramify.engine import assess

        receipt = assess("ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K")["receipt"]
        text = explain.explain_receipt(receipt)["text"].lower()
        self.assertIn("must not proceed", text)
        self.assertIn("recall", text)


if __name__ == "__main__":
    unittest.main()

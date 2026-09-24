"""The agent adapter — component 6.

These tests run with no framework and no model installed, which is the point.
The demonstration must work in that state, so the absence path is the one that
gets exercised on every run.
"""

import os
import unittest
from unittest import mock

from ramify.agent import explain, tools
from ramify.agent.langgraph_adapter import LangGraphAdapter
from ramify.agent.protocol import AgentAdapter, Interpretation
from ramify.crypto.sign import verify_receipt

# The suite must not depend on whether a model happens to be installed on the
# machine running it, or on reaching a daemon over the network. Every test here
# pins the flag rather than inferring the answer from the environment.
no_agent = mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "1"})


class TestAdapterContract(unittest.TestCase):
    def test_the_langgraph_adapter_satisfies_the_protocol(self):
        self.assertIsInstance(LangGraphAdapter(), AgentAdapter)

    @no_agent
    def test_the_disable_flag_takes_the_adapter_out(self):
        self.assertFalse(LangGraphAdapter().available())

    def test_an_unreachable_model_reports_unavailable(self):
        # Rather than raising into the caller mid-demonstration.
        adapter = LangGraphAdapter(model="no-such-model", base_url="http://127.0.0.1:1")
        self.assertFalse(adapter.available())

    @no_agent
    def test_an_unavailable_adapter_is_not_used(self):
        result = explain.explain_receipt({"product_name": "X", "objective_posture": "allow"})
        self.assertEqual(result["source"], "deterministic_summary")

    @no_agent
    def test_the_demonstration_works_with_no_model_at_all(self):
        from ramify.engine import assess

        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        result = explain.explain_receipt(receipt)
        self.assertEqual(result["source"], "deterministic_summary")
        self.assertTrue(result["text"])
        self.assertTrue(verify_receipt(receipt)["verified"])


class TestToolSurface(unittest.TestCase):
    def test_no_tool_can_author_a_verdict(self):
        # The whole architecture rests on this. If a tool existed that let a
        # model set a posture, everything else would be decoration.
        names = {spec["name"] for spec in tools.TOOL_SPECS}
        self.assertEqual(names, {"search_products", "assess_product", "list_products"})

    def test_assess_returns_an_already_sealed_receipt(self):
        result = tools.assess_product("ramify:demo:supp:apex-mg-glyc-120")
        self.assertIn("payload_hash", result["receipt"])
        self.assertTrue(verify_receipt(result["receipt"])["verified"])

    def test_the_tool_hands_back_a_copy(self):
        # A model mutating its tool result must not reach the stored receipt.
        first = tools.assess_product("ramify:demo:supp:apex-mg-glyc-120")
        first["receipt"]["actor_decision"] = "tampered"
        second = tools.assess_product("ramify:demo:supp:apex-mg-glyc-120")
        self.assertEqual(second["actor_decision"], "allow")

    def test_search_returns_nothing_rather_than_guessing(self):
        self.assertEqual(tools.search_products("hydraulic excavator parts"), [])

    def test_search_finds_a_real_product(self):
        results = tools.search_products("magnesium glycinate capsules")
        self.assertTrue(results)
        self.assertEqual(results[0]["subject_ref"], "ramify:demo:supp:apex-mg-glyc-120")


class TestDeterministicSummary(unittest.TestCase):
    def test_it_reports_the_posture_it_was_given(self):
        from ramify.engine import assess

        for subject, expected in (
            ("ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "must not proceed"),
            ("ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z", "a person decides"),
            ("ramify:demo:supp:apex-mg-glyc-120", "may proceed"),
        ):
            with self.subTest(subject=subject):
                receipt = assess(subject)["receipt"]
                self.assertIn(expected, explain.deterministic_summary(receipt))

    def test_it_explains_narrowing_without_changing_the_facts(self):
        from ramify.engine import assess

        receipt = assess("ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "procurement_v1")[
            "receipt"
        ]
        text = explain.deterministic_summary(receipt)
        self.assertIn("tightens from allow to hold", text)
        self.assertIn("The facts about the product did not change", text)

    def test_it_names_a_replacement_when_one_exists(self):
        from ramify.engine import assess

        receipt = assess("ramify:demo:supp:stonefield-zinc-gluc-50-90")["receipt"]
        self.assertIn("A replacement is available", explain.deterministic_summary(receipt))

    def test_it_always_states_the_permitted_action(self):
        from ramify.data import seed
        from ramify.engine import assess

        for subject_ref in seed.subjects():
            with self.subTest(subject=subject_ref):
                receipt = assess(subject_ref)["receipt"]
                self.assertIn("permitted to", explain.deterministic_summary(receipt))


@unittest.skipUnless(
    os.environ.get("RAMIFY_TEST_LIVE_MODEL") == "1",
    "set RAMIFY_TEST_LIVE_MODEL=1 with a local model running",
)
class TestLiveModel(unittest.TestCase):
    """Opt-in. Requires langgraph, langchain-ollama and a running daemon.

    Kept off the default run so the suite stays offline and fast, but present
    so the live path is covered rather than only reasoned about.
    """

    def setUp(self):
        self.adapter = LangGraphAdapter(model=os.environ.get("RAMIFY_LOCAL_MODEL", "llama3"))
        if not self.adapter.available():
            self.skipTest("no reachable model")

    def test_the_engine_decides_and_the_model_only_describes(self):
        turn = self.adapter.run_turn("nitrile examination gloves medium", "consumer_v1")
        self.assertEqual(turn["assessment"]["actor_decision"], "block")
        self.assertTrue(verify_receipt(turn["assessment"]["receipt"])["verified"])
        self.assertTrue(turn["explanation_is_presentation_only"])

    def test_a_model_naming_an_unknown_product_is_ignored(self):
        # The one place a hallucination could reach the engine. It is checked
        # against the catalogue rather than trusted.
        reading = self.adapter.interpret("a product that does not exist anywhere", [])
        if reading.identifier is not None:
            self.assertIn(
                reading.identifier, {p["subject_ref"] for p in tools.list_products()}
            )


class TestInterpretation(unittest.TestCase):
    def test_the_dataclass_carries_no_verdict_field(self):
        # An adapter returns what the user asked for, never what the answer is.
        fields = set(Interpretation.__dataclass_fields__)
        self.assertEqual(fields, {"identifier", "actor_ref", "confidence", "note"})
        for forbidden in ("posture", "verdict", "decision", "reason_codes"):
            self.assertNotIn(forbidden, fields)


if __name__ == "__main__":
    unittest.main()

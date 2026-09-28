"""Regression checks for the optional LangGraph + Ollama presentation layer.

These tests intentionally do not need Ollama or the third-party agent packages.
They verify the guard rails around the adapter so the normal offline suite stays
fast and deterministic.
"""

import os
import unittest
from unittest import mock

from ramify.agent.langgraph_adapter import (
    DEFAULT_MODEL,
    LangGraphAdapter,
    _json_object,
    _loopback_url,
    _model_matches,
    runtime_status,
)


class _Message:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    def __init__(self, content):
        self.content = content

    def invoke(self, _messages):
        return _Message(self.content)


class TestLocalModelReadiness(unittest.TestCase):
    def test_client_default_is_llama31(self):
        self.assertEqual(DEFAULT_MODEL, "llama3.1")

    def test_latest_tag_matches_short_model_name(self):
        self.assertTrue(_model_matches("llama3.1", "llama3.1:latest"))
        self.assertTrue(_model_matches("llama3.1:latest", "llama3.1"))
        self.assertFalse(_model_matches("llama3.1", "llama3.2:latest"))

    def test_only_loopback_ollama_endpoints_are_accepted(self):
        self.assertTrue(_loopback_url("http://127.0.0.1:11434"))
        self.assertTrue(_loopback_url("http://localhost:11434"))
        self.assertTrue(_loopback_url("http://[::1]:11434"))
        self.assertFalse(_loopback_url("https://ollama.example.com"))

    @mock.patch("ramify.agent.langgraph_adapter._local_json")
    @mock.patch("ramify.agent.langgraph_adapter._package_present", return_value=False)
    def test_missing_agent_packages_never_attempt_network(self, _packages, local_json):
        status = runtime_status()
        self.assertFalse(status["local_model_available"])
        self.assertFalse(status["dependencies_installed"])
        local_json.assert_not_called()

    def test_ready_means_framework_daemon_and_model_are_all_present(self):
        with mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "0"}), mock.patch(
            "ramify.agent.langgraph_adapter._package_present", return_value=True
        ), mock.patch(
            "ramify.agent.langgraph_adapter._local_json",
            return_value={"models": [{"name": "llama3.1:latest"}]},
        ):
            status = runtime_status(timeout=0.01)
        self.assertTrue(status["local_model_available"])
        self.assertTrue(status["ollama_daemon_reachable"])
        self.assertTrue(status["model_available"])
        self.assertEqual(status["decision_authority"], "deterministic_ramify_engine_only")




class TestInterpreterRouting(unittest.TestCase):
    def test_exact_identifier_bypasses_the_llm(self):
        from ramify.agent import interpreter

        ref = "ramify:demo:supp:apex-mg-glyc-120"
        with mock.patch(
            "ramify.agent.interpreter._try_local_model",
            side_effect=AssertionError("exact identifier should not reach model"),
        ):
            reading = interpreter.interpret(ref, mode="auto")
        self.assertEqual(reading["identifier"], ref)
        self.assertEqual(reading["source"], "exact_identifier")


    def test_single_trusted_candidate_bypasses_llm_even_for_sentence(self):
        from ramify.agent import interpreter

        ref = "ramify:demo:supp:apex-mg-glyc-120"
        with mock.patch(
            "ramify.agent.interpreter._try_local_model",
            side_effect=AssertionError("selected catalogue item should not reach model"),
        ):
            reading = interpreter.interpret(
                "Check Apex Magnesium Glycinate from the selected seller.",
                mode="auto",
                candidate_refs=[ref],
            )
        self.assertEqual(reading["identifier"], ref)
        self.assertEqual(reading["source"], "selected_catalogue_item")
        self.assertLess(reading["latency_ms"], 100)

    def test_human_request_fluff_does_not_make_every_product_tie(self):
        from ramify.agent import interpreter

        reading = interpreter.deterministic_interpret("I need the N95 mask in the catalogue.")
        self.assertEqual(reading["identifier"], "ramify:demo:ppe:covelane-n95-resp-b2026-01-B")

    def test_default_presentation_timeout_is_five_seconds(self):
        from ramify.agent import interpreter

        self.assertEqual(interpreter.LOCAL_MODEL_CALL_TIMEOUT_SECONDS, 5.0)

    def test_explicit_candidate_prevents_switching_product(self):
        from ramify.agent import interpreter

        selected = "ramify:demo:supp:apex-mg-glyc-120"
        other = "ramify:demo:supp:greenline-ashw-ksm66-90"
        reading = interpreter.deterministic_interpret(
            "Greenline Ashwagandha", candidate_refs=[selected]
        )
        self.assertNotEqual(reading.get("identifier"), other)

class TestModelOutputBoundary(unittest.TestCase):
    def setUp(self):
        self.adapter = LangGraphAdapter()
        self.candidates = [
            {
                "subject_ref": "ramify:demo:supp:apex-mg-glyc-120",
                "name": "Apex Magnesium Glycinate",
            }
        ]

    def _reading(self, content):
        self.adapter._ensure_model = lambda: _FakeModel(content)
        return self.adapter._interpret_with_model("magnesium capsules", self.candidates)

    def test_json_fence_is_tolerated_without_parsing_prose(self):
        parsed = _json_object('```json\n{"identifier": null, "confidence": 0.2, "note": "no match"}\n```')
        self.assertEqual(parsed["note"], "no match")

    def test_unknown_identifier_is_discarded_before_engine_boundary(self):
        reading = self._reading(
            '{"identifier":"ramify:invented:item","confidence":0.99,"note":"certain"}'
        )
        self.assertIsNone(reading.identifier)
        self.assertEqual(reading.confidence, 0.0)
        self.assertIn("discarded", reading.note.lower())

    def test_null_identifier_is_a_valid_no_match(self):
        reading = self._reading('{"identifier":null,"confidence":0.3,"note":"no clear match"}')
        self.assertIsNone(reading.identifier)
        self.assertEqual(reading.confidence, 0.3)

    def test_confidence_is_clamped(self):
        reading = self._reading(
            '{"identifier":"ramify:demo:supp:apex-mg-glyc-120","confidence":4.2,"note":"match"}'
        )
        self.assertEqual(reading.identifier, "ramify:demo:supp:apex-mg-glyc-120")
        self.assertEqual(reading.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()

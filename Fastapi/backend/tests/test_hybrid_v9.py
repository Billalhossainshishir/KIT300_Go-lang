"""Hybrid additions: friend logic, client feedback and humanised pages."""

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from ramify.api.app import app
from ramify.agent import interpreter

client = TestClient(app)


class TestPlainEnglishInterpretation(unittest.TestCase):
    @mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "1"})
    def test_plain_english_maps_only_to_a_known_catalogue_item(self):
        body = client.post(
            "/api/v0/interpret",
            json={"request_text": "Please buy the Apex magnesium capsules", "actor_ref": "consumer_v1"},
        ).json()
        self.assertEqual(body["identifier"], "ramify:demo:supp:apex-mg-glyc-120")
        self.assertFalse(body["authoritative"])
        self.assertIn("deterministic", body["source"])

    @mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "1"})
    def test_unknown_request_is_not_invented(self):
        body = client.post(
            "/api/v0/interpret", json={"request_text": "buy lunar reactor fuel"}
        ).json()
        self.assertIsNone(body["identifier"])
        self.assertEqual(body["confidence"], 0.0)

    def test_agent_status_states_the_boundary(self):
        body = client.get("/api/v0/agent/status").json()
        self.assertTrue(body["fallback_available"])
        self.assertIn("deterministic engine", body["boundary"])


class TestHumanAuthorityAndBasket(unittest.TestCase):
    def setUp(self):
        client.delete("/api/v0/cart")

    def test_human_override_is_linked_and_can_authorise_one_simulated_line(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"},
        ).json()
        self.assertEqual(assessed["actor_decision"], "hold")
        reviewed = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": assessed["receipt_ref"], "outcome": "overridden"},
        ).json()
        successor = reviewed["receipt"]
        self.assertEqual(successor["supersedes_receipt"], assessed["receipt_ref"])
        self.assertEqual(successor["actor_decision"], "hold")
        self.assertIn("add_to_mock_cart", successor["human_authorised_actions"])
        added = client.post(
            "/api/v0/cart/add", json={"receipt_ref": successor["receipt_id"]}
        )
        self.assertEqual(added.status_code, 200)

    def test_recall_is_never_sent_to_human_review_queue(self):
        result = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"},
        ).json()
        self.assertEqual(result["objective_posture"], "block")
        queue = client.get("/api/v0/review/queue").json()["open"]
        self.assertNotIn(result["receipt_ref"], {row["receipt_id"] for row in queue})


class TestHumanisedPages(unittest.TestCase):
    def test_new_pages_are_served(self):
        for path in ("/", "/shop", "/demo", "/human-receipt", "/technical"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_client_coverage_is_visible(self):
        body = client.get("/api/v0/demo/coverage").json()
        self.assertEqual(body["product_count"], 12)
        self.assertEqual(body["actor_count"], 5)
        self.assertGreaterEqual(body["scenario_count"], 17)
        self.assertGreaterEqual(body["evidence_count"], 20)

    def test_transition_matrix_is_published(self):
        body = client.get("/api/v0/vocabulary").json()
        matrix = body["transitions"]
        self.assertTrue(matrix["rows"])
        self.assertTrue(any(row["kind"] == "widens" and not row["permitted"] for row in matrix["rows"]))


class TestOptionalFrameworkBoundary(unittest.TestCase):
    def test_both_adapters_implement_the_same_narrow_protocol(self):
        from ramify.agent.langgraph_adapter import LangGraphAdapter
        from ramify.agent.pydanticai_adapter import PydanticAIAdapter
        from ramify.agent.protocol import AgentAdapter

        self.assertIsInstance(LangGraphAdapter(), AgentAdapter)
        self.assertIsInstance(PydanticAIAdapter(), AgentAdapter)


if __name__ == "__main__":
    unittest.main()

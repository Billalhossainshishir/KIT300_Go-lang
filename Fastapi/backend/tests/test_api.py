"""The HTTP surface.

Exercised through FastAPI's test client, which runs the real application
including validation, so a malformed request is rejected the same way it would
be over the wire.
"""

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from ramify.api.app import app

client = TestClient(app)


class TestPrimitiveEndpoints(unittest.TestCase):
    def test_healthz(self):
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_identify_resolves_a_gtin(self):
        response = client.post("/api/v0/identify", json={"identifier": "GTIN:09312345678901"})
        body = response.json()
        self.assertTrue(body["resolved"])
        self.assertEqual(body["subject_ref"], "ramify:demo:supp:apex-mg-glyc-120")

    def test_identify_reports_an_unknown_identifier_honestly(self):
        body = client.post("/api/v0/identify", json={"identifier": "GTIN:0000"}).json()
        self.assertFalse(body["resolved"])
        self.assertNotIn("confidence", body)
        self.assertEqual(body["match_method"], "no_exact_match")
        self.assertIsNone(body["subject_ref"])

    def test_a_shared_gtin_is_ambiguous_rather_than_guessed(self):
        # Two Brightway batches share a GTIN. Picking one arbitrarily would be
        # worse than saying it cannot be narrowed.
        body = client.post("/api/v0/identify", json={"identifier": "09312345678902"}).json()
        self.assertFalse(body["resolved"])
        self.assertEqual(body["next_action"], "disambiguate")
        self.assertEqual(len(body["candidates"]), 2)

    def test_resolve_reports_observed_for_an_unknown_subject(self):
        body = client.post("/api/v0/resolve", json={"subject_ref": "ramify:demo:supp:nope"}).json()
        self.assertEqual(body["canonical_state"], "observed")
        self.assertFalse(body["known"])

    def test_status_distinguishes_unknown_from_clean(self):
        # "No record held" is not the same as "no recall exists".
        body = client.post("/api/v0/status", json={"subject_ref": "ramify:demo:supp:nope"}).json()
        self.assertEqual(body["standing"], "unknown")
        self.assertNotEqual(body["standing"], "no_active_recall")

    def test_verify_returns_seven_checks(self):
        body = client.post(
            "/api/v0/verify", json={"subject_ref": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        self.assertEqual(len(body["check_results"]), 7)
        self.assertEqual(body["policy_status"], "demonstration_only")

    def test_malformed_request_is_rejected_at_the_edge(self):
        self.assertEqual(client.post("/api/v0/identify", json={}).status_code, 422)
        self.assertEqual(
            client.post("/api/v0/identify", json={"identifier": ""}).status_code, 422
        )

    def test_an_unknown_actor_profile_is_a_client_error(self):
        response = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "invented"},
        )
        self.assertEqual(response.status_code, 400)


class TestAssessEndpoint(unittest.TestCase):
    def test_assess_returns_a_verifying_receipt(self):
        body = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        report = client.post("/api/v0/receipt/verify", json=body["receipt"]).json()
        self.assertTrue(report["verified"])

    def test_the_traffic_light_is_in_the_envelope_not_the_receipt(self):
        body = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        self.assertEqual(body["traffic_light"]["colour"], "green")
        self.assertEqual(body["traffic_light"]["label"], "Approved")
        self.assertNotIn("traffic_light", body["receipt"])
        self.assertNotIn("colour", body["receipt"])

    def test_tampering_is_rejected_over_http(self):
        body = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"},
        ).json()
        receipt = dict(body["receipt"])
        self.assertEqual(receipt["actor_decision"], "block")
        receipt["actor_decision"] = "allow"
        report = client.post("/api/v0/receipt/verify", json=receipt).json()
        self.assertFalse(report["verified"])

    def test_the_verifier_reports_only_checks_it_ran(self):
        body = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        report = client.post("/api/v0/receipt/verify", json=body["receipt"]).json()
        names = {check["name"] for check in report["checks"]}
        self.assertEqual(
            names,
            {"hash_valid", "signature_valid", "issuer_refs_known", "scope_valid", "fresh"},
        )
        for check in report["checks"]:
            self.assertTrue(check["detail"], "a check reported no detail")


class TestHumanReview(unittest.TestCase):
    def test_review_appends_rather_than_overwrites(self):
        # Client direction item 5: a human-review decision appends a linked
        # superseding receipt. The original must survive unchanged.
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"},
        ).json()
        original_id = assessed["receipt_ref"]

        reviewed = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": original_id, "outcome": "confirmed", "reviewer_note": "checked"},
        ).json()

        self.assertEqual(reviewed["supersedes"], original_id)
        self.assertNotEqual(reviewed["receipt_ref"], original_id)

        from ramify.receipt import store

        self.assertEqual(store.get(original_id)["payload_hash"], assessed["receipt"]["payload_hash"])

    def test_the_superseding_receipt_verifies(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"},
        ).json()
        reviewed = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": assessed["receipt_ref"], "outcome": "overridden"},
        ).json()
        report = client.post("/api/v0/receipt/verify", json=reviewed["receipt"]).json()
        self.assertTrue(report["verified"])

    def test_reviewing_an_unknown_receipt_is_a_404(self):
        response = client.post(
            "/api/v0/receipt/review", json={"receipt_id": "nope", "outcome": "confirmed"}
        )
        self.assertEqual(response.status_code, 404)

    def test_an_invalid_review_outcome_is_rejected(self):
        response = client.post(
            "/api/v0/receipt/review", json={"receipt_id": "x", "outcome": "approve_everything"}
        )
        self.assertEqual(response.status_code, 422)


class TestExplanationEndpoint(unittest.TestCase):
    # Pinned so the suite does not depend on whether a local model happens to
    # be running on the machine executing it.
    @mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "1"})
    def test_the_explanation_is_labelled_presentation(self):
        assessed = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        body = client.post("/api/v0/explain", json={"receipt": assessed["receipt"]}).json()
        self.assertTrue(body["presentation_only"])
        self.assertFalse(body["authoritative"])
        self.assertTrue(body["explanation"])

    @mock.patch.dict(os.environ, {"RAMIFY_DISABLE_AGENT": "1"})
    def test_explaining_does_not_change_the_stored_receipt(self):
        assessed = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"},
        ).json()
        client.post("/api/v0/explain", json={"receipt": assessed["receipt"]})

        from ramify.receipt import store

        stored = store.get(assessed["receipt_ref"])
        self.assertEqual(stored["actor_decision"], "block")
        self.assertEqual(stored["payload_hash"], assessed["receipt"]["payload_hash"])


class TestNoStaleBuild(unittest.TestCase):
    """A cached asset does not announce itself — the page simply looks like
    nothing changed, which is the worst way to discover a stale build.
    """

    def test_nothing_is_cacheable(self):
        for path in ("/", "/style.css", "/shell.js", "/api/v0/catalogue"):
            with self.subTest(path=path):
                headers = client.get(path).headers
                self.assertIn("no-store", headers["cache-control"])

    def test_the_build_id_is_reported(self):
        # So "am I looking at the current build?" is answerable by looking.
        self.assertTrue(client.get("/healthz").json()["build"])
        self.assertTrue(client.get("/api/v0/catalogue").json()["build"])


class TestInterfaceAssets(unittest.TestCase):
    def test_every_page_is_served(self):
        for path in ("/", "/agents", "/review", "/cart", "/activity", "/about", "/help"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_every_asset_is_served(self):
        for path in (
            "/style.css",
            "/shell.js",
            "/console.js",
            "/agents.js",
            "/review.js",
            "/cart.js",
            "/activity.js",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)

    def test_only_web_assets_are_reachable(self):
        # The page route serves files by name, so it must not become a way to
        # read anything else on disk.
        for path in ("/../pyproject.toml", "/..%2fpyproject.toml", "/demo_seed.json", "/nope"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_the_catalogue_carries_the_synthetic_notice(self):
        body = client.get("/api/v0/catalogue").json()
        self.assertIn("Synthetic", body["notice"])
        self.assertEqual(len(body["products"]), 12)

    def test_the_catalogue_prices_products_in_integer_cents(self):
        for product in client.get("/api/v0/catalogue").json()["products"]:
            with self.subTest(product=product["subject_ref"]):
                self.assertIsInstance(product["price_cents"], int)


class TestComparison(unittest.TestCase):
    def test_every_persona_sees_the_same_objective_posture(self):
        # The architecture in one assertion: the product assessment does not
        # know who is asking.
        for identifier in (
            "ramify:demo:supp:apex-mg-glyc-120",
            "ramify:demo:supp:greenline-ashw-ksm66-90",
            "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K",
        ):
            with self.subTest(identifier=identifier):
                body = client.post("/api/v0/compare", json={"identifier": identifier}).json()
                self.assertTrue(body["objective_agreed"])
                self.assertEqual(len(body["personas"]), 5)

    def test_personas_reach_different_decisions_from_the_same_facts(self):
        body = client.post(
            "/api/v0/compare", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        decisions = {p["actor_ref"]: p["decision"] for p in body["personas"]}
        self.assertEqual(decisions["consumer_v1"], "allow")
        # A$34.95 is over the budget agent's A$30 ceiling.
        self.assertEqual(decisions["budget_guard_v1"], "hold")

    def test_quantity_reaches_the_budget_check_but_not_the_assessment(self):
        one = client.post(
            "/api/v0/compare",
            json={"identifier": "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "quantity": 1},
        ).json()
        many = client.post(
            "/api/v0/compare",
            json={"identifier": "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "quantity": 10},
        ).json()

        self.assertEqual(one["objective_posture"], many["objective_posture"])

        budget_one = next(p for p in one["personas"] if p["actor_ref"] == "budget_guard_v1")
        budget_many = next(p for p in many["personas"] if p["actor_ref"] == "budget_guard_v1")
        self.assertEqual(budget_one["decision"], "allow")
        self.assertEqual(budget_many["decision"], "hold")


class TestReviewQueue(unittest.TestCase):
    def test_a_held_receipt_joins_the_queue_and_leaves_once_answered(self):
        assessed = client.post(
            "/api/v0/assess",
            json={
                "identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z",
                "actor_ref": "consumer_v1",
            },
        ).json()
        receipt_id = assessed["receipt_ref"]
        self.assertTrue(assessed["requires_human"])

        open_ids = [r["receipt_id"] for r in client.get("/api/v0/review/queue").json()["open"]]
        self.assertIn(receipt_id, open_ids)

        client.post(
            "/api/v0/receipt/review", json={"receipt_id": receipt_id, "outcome": "confirmed"}
        )

        queue = client.get("/api/v0/review/queue").json()
        self.assertNotIn(receipt_id, [r["receipt_id"] for r in queue["open"]])
        self.assertIn(receipt_id, [r["supersedes_receipt"] for r in queue["resolved"]])

    def test_an_approved_result_never_joins_the_queue(self):
        assessed = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        self.assertFalse(assessed["requires_human"])
        open_ids = [r["receipt_id"] for r in client.get("/api/v0/review/queue").json()["open"]]
        self.assertNotIn(assessed["receipt_ref"], open_ids)

    def test_a_single_receipt_can_be_fetched_back(self):
        assessed = client.post(
            "/api/v0/assess", json={"identifier": "ramify:demo:supp:apex-mg-glyc-120"}
        ).json()
        fetched = client.get(f"/api/v0/receipt/{assessed['receipt_ref']}").json()
        self.assertEqual(fetched["payload_hash"], assessed["receipt"]["payload_hash"])


if __name__ == "__main__":
    unittest.main()

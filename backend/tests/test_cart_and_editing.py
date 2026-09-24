"""The basket, the order record, and customer-edited agents.

Two properties carry most of the weight here.

Nothing reaches the basket without a receipt that permitted a purchase, and
that is checked on the server against the sealed receipt rather than trusted
from the browser. A front end is not a security boundary.

No edit a customer can make produces an agent more permissive than the product
assessment allows. That is a property of what is editable — narrowing rules and
permitted actions are derived, never typed — so it is tested by trying to
subvert it rather than by reading the code.
"""

import unittest

from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import cart
from ramify.api.app import app
from ramify.policy import profiles
from ramify.ratify.precedence import RESTRICTIVENESS

client = TestClient(app)

CLEAN = "ramify:demo:supp:apex-mg-glyc-120"
WARNED = "ramify:demo:supp:greenline-ashw-ksm66-90"
RECALLED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
ADVISORY = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"


def assess(identifier, actor="consumer_v1", quantity=1):
    return client.post(
        "/api/v0/assess",
        json={"identifier": identifier, "actor_ref": actor, "quantity": quantity},
    ).json()


class TestCart(unittest.TestCase):
    def setUp(self):
        cart.clear()

    def test_a_clean_result_can_be_added(self):
        result = assess(CLEAN)
        self.assertTrue(result["can_add_to_cart"])
        response = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cart"]["line_count"], 1)

    def test_a_recalled_product_is_refused(self):
        result = assess(RECALLED)
        self.assertFalse(result["can_add_to_cart"])
        response = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 409)
        self.assertIn("block", response.json()["detail"])

    def test_a_held_product_is_refused(self):
        result = assess(ADVISORY)
        response = client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        self.assertEqual(response.status_code, 409)

    def test_the_browser_cannot_talk_its_way_past_the_check(self):
        # The receipt is re-read server-side, so a caller that simply asserts a
        # different outcome gets nowhere.
        response = client.post("/api/v0/cart/add", json={"receipt_ref": "ramify:demo:rcpt:invented"})
        self.assertEqual(response.status_code, 409)

    def test_every_line_names_the_receipt_that_admitted_it(self):
        result = assess(CLEAN, quantity=2)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        line = client.get("/api/v0/cart").json()["lines"][0]
        self.assertEqual(line["receipt_ref"], result["receipt_ref"])
        self.assertEqual(line["payload_hash"], result["receipt"]["payload_hash"])
        self.assertEqual(line["quantity"], 2)

    def test_totals_are_integer_cents(self):
        result = assess(CLEAN, quantity=3)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        basket = client.get("/api/v0/cart").json()
        self.assertIsInstance(basket["total_cents"], int)
        self.assertEqual(basket["total_cents"], 3495 * 3)

    def test_a_line_can_be_removed(self):
        result = assess(CLEAN)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        line_id = client.get("/api/v0/cart").json()["lines"][0]["line_id"]
        self.assertEqual(client.delete(f"/api/v0/cart/line/{line_id}").json()["line_count"], 0)

    def test_removing_a_line_that_is_not_there_is_a_404(self):
        self.assertEqual(client.delete("/api/v0/cart/line/nope").status_code, 404)

    def test_checkout_seals_a_verifiable_order_record(self):
        for _ in range(2):
            result = assess(CLEAN)
            client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})

        order = client.post("/api/v0/cart/checkout", json={}).json()["order"]
        self.assertEqual(order["line_count"], 2)
        report = client.post("/api/v0/receipt/verify", json=order).json()
        self.assertTrue(report["verified"], report["checks"])
        self.assertIn("No purchase was made", order["notice"])

    def test_an_order_record_is_checked_as_an_order_not_a_receipt(self):
        # It carries no issuers and no standing, so checking it for those would
        # fail it for lacking what it was never meant to have.
        result = assess(CLEAN)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        order = client.post("/api/v0/cart/checkout", json={}).json()["order"]
        names = {c["name"] for c in client.post("/api/v0/receipt/verify", json=order).json()["checks"]}
        self.assertEqual(names, {"hash_valid", "signature_valid", "lines_intact"})

    def test_an_order_quoting_a_stale_hash_fails(self):
        result = assess(CLEAN)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        order = client.post("/api/v0/cart/checkout", json={}).json()["order"]
        order["lines"][0]["receipt_hash"] = "sha256:" + "0" * 64
        report = client.post("/api/v0/receipt/verify", json=order).json()
        self.assertFalse(report["verified"])

    def test_checkout_empties_the_basket(self):
        result = assess(CLEAN)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        after = client.post("/api/v0/cart/checkout", json={}).json()["cart"]
        self.assertEqual(after["line_count"], 0)

    def test_an_empty_basket_cannot_be_checked_out(self):
        self.assertEqual(client.post("/api/v0/cart/checkout", json={}).status_code, 409)

    def test_the_order_record_names_every_receipt(self):
        result = assess(CLEAN)
        client.post("/api/v0/cart/add", json={"receipt_ref": result["receipt_ref"]})
        order = client.post("/api/v0/cart/checkout", json={}).json()["order"]
        self.assertEqual(order["lines"][0]["receipt_ref"], result["receipt_ref"])
        self.assertEqual(order["lines"][0]["receipt_hash"], result["receipt"]["payload_hash"])


class TestEditingAnAgent(unittest.TestCase):
    def tearDown(self):
        profiles.reset_all()

    def test_a_shipped_agent_can_be_edited_and_reset(self):
        client.put(
            "/api/v0/agents/consumer_v1",
            json={"label": "My shopper", "autonomy_level": "none", "budget_limit_cents": 1000},
        )
        edited = profiles.profile("consumer_v1")
        self.assertEqual(edited["label"], "My shopper")
        self.assertTrue(edited["edited"])

        client.delete("/api/v0/agents/consumer_v1")
        self.assertEqual(profiles.profile("consumer_v1")["label"], "Consumer shopping agent")

    def test_a_new_agent_can_be_created_and_deleted(self):
        created = client.post(
            "/api/v0/agents", json={"label": "Weekend shopper", "autonomy_level": "clean_only"}
        ).json()
        self.assertEqual(created["ref"], "custom_weekend_shopper")
        self.assertIn(created["ref"], profiles.all_profiles())

        client.delete(f"/api/v0/agents/{created['ref']}")
        self.assertNotIn(created["ref"], profiles.all_profiles())

    def test_an_edited_agent_actually_changes_its_decisions(self):
        before = assess(CLEAN, "consumer_v1")["actor_decision"]
        self.assertEqual(before, "allow")

        client.put(
            "/api/v0/agents/consumer_v1",
            json={"label": "Frugal shopper", "budget_limit_cents": 500},
        )
        after = assess(CLEAN, "consumer_v1")
        self.assertEqual(after["actor_decision"], "hold")
        self.assertIn("line_total_exceeds_agent_budget", after["reason_codes"])

    def test_a_custom_agent_still_cannot_touch_a_recalled_product(self):
        # The whole point of deriving the rules rather than accepting them.
        created = client.post(
            "/api/v0/agents",
            json={
                "label": "Buys anything",
                "autonomy_level": "clean_or_warned",
                "budget_limit_cents": None,
            },
        ).json()
        result = assess(RECALLED, created["ref"])
        self.assertEqual(result["actor_decision"], "block")
        self.assertEqual(result["permitted_actions"], ["halt"])
        self.assertFalse(result["can_add_to_cart"])

    def test_no_edit_can_produce_a_widening_agent(self):
        for autonomy in ("none", "clean_only", "clean_or_warned"):
            created = client.post(
                "/api/v0/agents", json={"label": f"Trial {autonomy}", "autonomy_level": autonomy}
            ).json()
            for subject_ref in (CLEAN, WARNED, ADVISORY, RECALLED):
                with self.subTest(autonomy=autonomy, subject=subject_ref):
                    result = assess(subject_ref, created["ref"])
                    self.assertGreaterEqual(
                        RESTRICTIVENESS[result["actor_decision"]],
                        RESTRICTIVENESS[result["objective_posture"]],
                    )

    def test_autonomy_can_never_be_granted_over_a_stopped_outcome(self):
        for autonomy in profiles.AUTONOMY_LEVELS.values():
            with self.subTest(autonomy=autonomy):
                for posture in ("hold", "escalate", "block"):
                    self.assertNotIn(posture, autonomy)

    def test_a_stopped_posture_never_permits_a_purchase(self):
        for profile in profiles.all_profiles().values():
            for posture in ("hold", "escalate", "block"):
                actions = profile["permitted_actions"][posture]
                with self.subTest(agent=profile["ref"], posture=posture):
                    for buying in ("purchase_autonomously", "add_to_mock_cart", "create_mock_requisition"):
                        self.assertNotIn(buying, actions)

    def test_an_agent_with_no_name_is_rejected(self):
        # Whitespace passes the length constraint at the edge and is caught by
        # the profile store, which is the right place for a rule about meaning
        # rather than shape.
        self.assertEqual(client.post("/api/v0/agents", json={"label": "  "}).status_code, 400)
        self.assertEqual(client.post("/api/v0/agents", json={"label": ""}).status_code, 422)

    def test_an_unknown_brand_is_rejected(self):
        response = client.post(
            "/api/v0/agents", json={"label": "Picky", "brand_allowlist": ["Not A Real Brand"]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Not a brand", response.json()["detail"])

    def test_an_unknown_seller_is_rejected(self):
        response = client.post(
            "/api/v0/agents", json={"label": "Picky", "approved_vendors": ["ramify:demo:seller:Nope"]}
        )
        self.assertEqual(response.status_code, 400)

    def test_a_negative_budget_is_rejected(self):
        response = client.post(
            "/api/v0/agents", json={"label": "Impossible", "budget_limit_cents": -100}
        )
        self.assertEqual(response.status_code, 422)

    def test_preview_compiles_without_saving(self):
        before = set(profiles.all_profiles())
        preview = client.post(
            "/api/v0/agents/preview", json={"label": "Just looking", "autonomy_level": "clean_only"}
        ).json()
        self.assertEqual(preview["permitted_actions"]["block"], ["halt"])
        self.assertEqual(set(profiles.all_profiles()), before)


class TestEscalationKinds(unittest.TestCase):
    """A recall and a spending limit both stop the agent. They are not the same
    event, and the interface should not make a person read reason codes to tell
    them apart.
    """

    CASES = (
        (RECALLED, "consumer_v1", "safety", False),
        (ADVISORY, "consumer_v1", "safety", True),
        (WARNED, "procurement_v1", "evidence", True),
        ("ramify:demo:ppe:covelane-n95-resp-b2026-01-B", "procurement_v1", "authority", True),
        (CLEAN, "budget_guard_v1", "budget", True),
        ("ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "brand_loyal_v1", "arrangement", True),
        ("ramify:demo:supp:ridgeway-multivit-b2026-02-C", "consumer_v1", "evidence", True),
        ("no-such-product", "consumer_v1", "identity", True),
    )

    def test_each_kind_of_stop_is_classified(self):
        for subject_ref, actor, kind, requires_human in self.CASES:
            with self.subTest(subject=subject_ref, actor=actor):
                result = assess(subject_ref, actor)
                self.assertIsNotNone(result["escalation"])
                self.assertEqual(result["escalation"]["kind"], kind)
                self.assertEqual(result["escalation"]["requires_human"], requires_human)

    def test_a_green_result_has_no_stop_to_explain(self):
        self.assertIsNone(assess(CLEAN)["escalation"])

    def test_safety_outranks_a_commercial_reason(self):
        # A recalled batch that is also over budget is a safety stop, not a
        # spending one.
        result = assess(RECALLED, "budget_guard_v1")
        self.assertEqual(result["escalation"]["kind"], "safety")

    def test_a_rejection_says_nobody_decides(self):
        escalation = assess(RECALLED)["escalation"]
        self.assertFalse(escalation["requires_human"])
        self.assertIn("not open to a decision", escalation["decided_by"])

    def test_every_stop_names_who_decides(self):
        for subject_ref, actor, _, _ in self.CASES:
            with self.subTest(subject=subject_ref):
                self.assertTrue(assess(subject_ref, actor)["escalation"]["decided_by"])

    def test_commercial_stops_point_at_the_buyer_not_the_product(self):
        for subject_ref, actor in (
            (CLEAN, "budget_guard_v1"),
            ("ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "brand_loyal_v1"),
        ):
            with self.subTest(subject=subject_ref):
                escalation = assess(subject_ref, actor)["escalation"]
                self.assertEqual(escalation["tone"], "commercial")
                self.assertEqual(escalation["decided_by"], "You")


if __name__ == "__main__":
    unittest.main()

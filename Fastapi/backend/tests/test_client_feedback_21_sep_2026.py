"""Acceptance tests for David Male's consolidated feedback of 21 September 2026.

Each class is named for one task ID in that document and exercises its stated
acceptance criteria, not just the ordinary button-driven flow. Every case runs
against a throwaway ``RAMIFY_DATA_DIR``.
"""

import os
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import cart
from ramify.api.app import app
from ramify.crypto.canonical import rfc3339_nano
from ramify.crypto.sign import seal, verify_receipt
from ramify.data import seed
from ramify.receipt import store
from ramify.timing import now

client = TestClient(app)

HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"
BLOCKED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
ALLOWED = "ramify:demo:supp:apex-mg-glyc-120"


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def assess(self, subject_ref, actor_ref="consumer_v1"):
        response = client.post("/api/v0/assess", json={
            "identifier": subject_ref, "actor_ref": actor_ref,
            "quantity": 1, "context": "purchase",
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["receipt"]

    def review(self, receipt_id, outcome="overridden"):
        return client.post("/api/v0/receipt/review", json={"receipt_id": receipt_id, "outcome": outcome})

    def line_for(self, receipt):
        order = receipt["order"]
        return {
            "line_id": uuid.uuid4().hex[:12],
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "brand": (seed.subject(receipt["subject_ref"]) or {}).get("brand", ""),
            "quantity": int(order["quantity"]),
            "unit_price_cents": int(order["unit_price_cents"]),
            "line_total_cents": int(order["line_total_cents"]),
            "receipt_ref": receipt["receipt_id"],
            "payload_hash": receipt["payload_hash"],
            "actor_ref": receipt["actor_ref"],
            "actor_label": receipt["actor_label"],
            "objective_posture": receipt["objective_posture"],
            "actor_decision": receipt["actor_decision"],
            "unattended": receipt.get("selected_action") == "purchase_autonomously",
            "human_authorised": bool(receipt.get("human_authorised_actions")),
            "human_review_outcome": (receipt.get("human_review") or {}).get("outcome"),
            "supersedes_receipt": receipt.get("supersedes_receipt"),
            "added_at": rfc3339_nano(now()),
        }

    def write_lines(self, lines):
        basket = cart._read()
        basket["lines"] = lines
        cart._write(basket)

    def order_count(self):
        return len(cart._read()["orders"])


class TestA1CheckoutRechecksActionPermission(TempStoreCase):
    """A1: insert a matching line directly into local cart state; checkout refuses."""

    def _refused_with_no_order(self, receipt):
        self.write_lines([self.line_for(receipt)])
        with self.assertRaises(cart.CartRefused):
            cart.checkout()
        self.assertEqual(self.order_count(), 0)

    def test_blocked_receipt_line(self):
        self._refused_with_no_order(self.assess(BLOCKED))

    def test_held_receipt_without_human_authority(self):
        receipt = self.assess(HELD)
        self.assertFalse(receipt.get("human_authorised_actions"))
        self._refused_with_no_order(receipt)

    def test_procurement_only_receipt_in_a_consumer_basket(self):
        receipt = self.assess(ALLOWED, "procurement_v1")
        self.assertNotIn("add_to_mock_cart", receipt["permitted_actions"])
        self._refused_with_no_order(receipt)


class TestA2OneTimeAuthority(TempStoreCase):
    """A2: duplicates, replayed consumed references and competing checkouts."""

    def test_duplicated_line_produces_no_order(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])
        line = cart._read()["lines"][0]
        self.write_lines([line, dict(line, line_id=uuid.uuid4().hex[:12])])
        with self.assertRaises(cart.CartRefused):
            cart.checkout()
        self.assertEqual(self.order_count(), 0)

    def test_replaying_a_consumed_reference_produces_no_second_order(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])
        line = cart._read()["lines"][0]
        cart.checkout()
        self.assertEqual(self.order_count(), 1)

        self.write_lines([dict(line, line_id=uuid.uuid4().hex[:12])])
        with self.assertRaises(cart.CartRefused):
            cart.checkout()
        self.assertEqual(self.order_count(), 1)

    def test_competing_checkouts_yield_one_order(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])
        codes = []
        threads = [threading.Thread(target=lambda: codes.append(
            client.post("/api/v0/cart/checkout").status_code)) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(self.order_count(), 1)

    def test_the_order_verifier_rejects_duplicated_lines(self):
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])
        genuine = cart.checkout()
        self.assertTrue(verify_receipt(genuine)["integrity_verified"])

        forged = {k: v for k, v in genuine.items() if k not in ("payload_hash", "signature")}
        forged["lines"] = genuine["lines"] + genuine["lines"]
        forged["line_count"] = 2
        forged["item_count"] = 2 * genuine["item_count"]
        report = verify_receipt(seal(forged))
        self.assertFalse(report["lines_intact"], report)
        self.assertFalse(report["integrity_verified"])

    def test_the_order_verifier_rejects_a_line_its_receipt_never_permitted(self):
        blocked = self.assess(BLOCKED)
        line = self.line_for(blocked)
        record = {
            "schema_version": "0.4", "record_type": "order_record",
            "order_id": "ramify:demo:order:forged", "line_count": 1,
            "item_count": 1, "total_cents": line["line_total_cents"],
            "lines": [{
                "subject_ref": line["subject_ref"], "product_name": line["product_name"],
                "quantity": line["quantity"], "line_total_cents": line["line_total_cents"],
                "receipt_ref": line["receipt_ref"], "receipt_hash": line["payload_hash"],
                "actor_ref": line["actor_ref"], "objective_posture": line["objective_posture"],
                "actor_decision": line["actor_decision"], "human_authorised": False,
                "supersedes_receipt": None,
            }],
        }
        report = verify_receipt(seal(record))
        self.assertFalse(report["lines_intact"], report)


class TestA3AuthoriseOnceAcrossTheChain(TempStoreCase):
    """A3: approval is terminal before and after consumption, declines stay
    closed, concurrent reviews yield one outcome, and the root is unchanged."""

    def test_an_approved_successor_cannot_be_reviewed_before_consumption(self):
        successor = self.review(self.assess(HELD)["receipt_id"]).json()["receipt"]
        self.assertEqual(self.review(successor["receipt_id"]).status_code, 409)

    def test_an_approved_successor_cannot_be_reviewed_after_consumption(self):
        successor = self.review(self.assess(HELD)["receipt_id"]).json()["receipt"]
        cart.add(successor["receipt_id"])
        cart.checkout()
        self.assertEqual(self.review(successor["receipt_id"]).status_code, 409)
        self.assertEqual(self.order_count(), 1)

    def test_a_declined_chain_cannot_be_reopened(self):
        held = self.assess(HELD)
        declined = self.review(held["receipt_id"], outcome="confirmed").json()["receipt"]
        self.assertEqual(self.review(declined["receipt_id"]).status_code, 409)
        self.assertEqual(self.review(held["receipt_id"]).status_code, 409)

    def test_concurrent_reviews_yield_one_terminal_outcome(self):
        held = self.assess(HELD)
        codes = []
        threads = [threading.Thread(target=lambda: codes.append(
            self.review(held["receipt_id"]).status_code)) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(codes.count(200), 1, codes)

    def test_the_original_machine_receipt_is_unchanged(self):
        held = self.assess(HELD)
        self.review(held["receipt_id"])
        stored = store.get(held["receipt_id"])
        self.assertEqual(stored["payload_hash"], held["payload_hash"])
        self.assertTrue(verify_receipt(stored)["integrity_verified"])


class TestT1WideningIsStoppedAtTheRealGuard(unittest.TestCase):
    """T1: a recognised rule that applies, but whose candidate would widen.

    The earlier test used an unrecognised rule id, which never applies, so it
    passed without reaching the guard it claimed to test.
    """

    SUBJECT = seed.subject(ALLOWED)
    CASES = [
        # (objective posture, recognised rule, order that makes it apply)
        ("allow_with_warning", {"id": "warned_outcome_requires_review"}, {}),
        ("hold", {"id": "over_budget"}, {"line_total_cents": 999_999}),
        ("block", {"id": "price_unavailable_for_budget"}, {"line_total_cents": None}),
    ]

    def _profile(self, rule):
        return {
            "label": "Widening test profile",
            "budget_limit_cents": 100,
            "narrowing_rules": [{**rule, "narrow_to": "allow", "reason_code": "must_not_apply"}],
            "permitted_actions": {},
        }

    def test_an_applicable_widening_rule_is_ignored(self):
        from ramify.policy import actor as actor_policy
        for objective, rule, order in self.CASES:
            with self.subTest(objective=objective, rule=rule["id"]):
                profile = self._profile(rule)
                self.assertTrue(
                    actor_policy._rule_applies(profile["narrowing_rules"][0], objective,
                                               profile, self.SUBJECT, order),
                    "fixture must reach the guard, not fall through applicability",
                )
                with patch("ramify.policy.profiles.profile", return_value=profile):
                    result = actor_policy.apply(objective, "widening_test", self.SUBJECT, order)
                self.assertEqual(result.decision, objective)
                self.assertFalse(result.narrowed)
                self.assertEqual(result.applied_rules, [])
                self.assertNotIn("must_not_apply", result.reason_codes)

    def test_the_final_guard_rejects_a_widening_that_gets_past_the_rule_check(self):
        from ramify.policy import actor as actor_policy
        inverted = {"allow": 9, "allow_with_warning": 1, "hold": 2, "escalate": 3, "block": 4}
        objective, rule, order = self.CASES[0]
        with patch("ramify.policy.profiles.profile", return_value=self._profile(rule)), \
             patch.object(actor_policy, "RESTRICTIVENESS", inverted):
            with self.assertRaises(actor_policy.PolicyWouldWiden):
                actor_policy.apply(objective, "widening_test", self.SUBJECT, order)


class TestPOL1ReceiptsNameTheExactInputs(TempStoreCase):
    """POL1: an unknown reference fails, and content changes change identity."""

    def test_an_unknown_policy_reference_fails_explicitly(self):
        response = client.post("/api/v0/assess", json={
            "identifier": ALLOWED, "policy_ref": "ramify:demo:policy:unknown"})
        self.assertEqual(response.status_code, 400, response.text)

    def test_the_receipt_records_policy_and_dataset_digests(self):
        receipt = self.assess(ALLOWED)
        self.assertEqual(receipt["policy_ref"], seed.policy_pack()["policy_ref"])
        self.assertEqual(receipt["policy_digest"], seed.policy_digest())
        self.assertEqual(receipt["dataset_digest"], seed.dataset_digest())
        self.assertRegex(receipt["policy_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_changing_policy_content_changes_the_recorded_identity(self):
        before = engine.assess(ALLOWED, persist_receipt=False)["receipt"]
        altered = dict(seed.policy_pack(), notice="edited without changing the version label")
        with patch.object(seed, "policy_pack", return_value=altered):
            after = engine.assess(ALLOWED, persist_receipt=False)["receipt"]
        self.assertEqual(before["policy_version"], after["policy_version"])
        self.assertNotEqual(before["policy_digest"], after["policy_digest"])

    def test_changing_dataset_content_changes_the_recorded_identity(self):
        import copy
        before = engine.assess(ALLOWED, persist_receipt=False)["receipt"]
        altered = copy.deepcopy(seed.seed())
        altered["meta"]["notice"] = "edited without changing the snapshot label"
        with patch.object(seed, "seed", return_value=altered):
            after = engine.assess(ALLOWED, persist_receipt=False)["receipt"]
        self.assertEqual(before["data_snapshot"], after["data_snapshot"])
        self.assertNotEqual(before["dataset_digest"], after["dataset_digest"])

    def test_an_exported_receipt_maps_to_the_policy_file_in_its_pack(self):
        import hashlib
        import io
        import json
        import zipfile
        pack = zipfile.ZipFile(io.BytesIO(client.get("/api/v0/proof-pack").content))
        policy = json.loads(pack.read("policy/policy_pack_demo_v1.json"))
        digest = "sha256:" + hashlib.sha256(json.dumps(
            policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        receipt_name = next(n for n in pack.namelist() if n.startswith("receipts/"))
        receipt = json.loads(pack.read(receipt_name))
        self.assertEqual(receipt["policy_digest"], digest)


def _seed_script():
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"
    spec = importlib.util.spec_from_file_location("ramify_seed_script_k1", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestK1SigningIdentitySurvivesLossAndReset(TempStoreCase):
    """K1: reset clears transactions, not identity; a lost identity is an
    explicit recovery; exported receipts stay verifiable with retained keys."""

    def _reset(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _seed_script().do_reset()
        return buffer.getvalue()

    def test_reset_keeps_the_signer_and_earlier_receipts_verify(self):
        from ramify.crypto import keys
        exported = self.assess(ALLOWED)
        before = keys.signer_fingerprint()
        output = self._reset()
        self.assertEqual(keys.signer_fingerprint(), before)
        self.assertIn("Keys unchanged", output)
        self.assertTrue(verify_receipt(exported)["integrity_verified"])

    def test_reset_clears_transaction_data(self):
        from ramify.crypto import keys
        receipt = self.assess(ALLOWED)
        cart.add(receipt["receipt_id"])
        client.post("/api/v0/agents", json={"label": "Temporary helper"})
        self._reset()
        store_dir = keys.local_data_store()
        self.assertEqual(store.all_receipts(), [])
        self.assertEqual(cart.contents()["line_count"], 0)
        self.assertFalse((store_dir / "agent_profiles.json").exists())
        self.assertTrue((store_dir / "signer_key.json").exists())

    def test_missing_private_key_with_history_does_not_silently_rotate(self):
        from ramify.crypto import keys
        self.assess(ALLOWED)
        (keys.local_data_store() / "signer_key.json").unlink()
        with self.assertRaises(keys.SignerKeyError):
            keys.load_signer_private_key()

    def test_explicit_recovery_keeps_exported_receipts_verifiable(self):
        from ramify.crypto import keys
        exported = self.assess(ALLOWED)
        old = keys.signer_fingerprint()
        (keys.local_data_store() / "signer_key.json").unlink()

        output = self._reset()
        self.assertNotEqual(keys.signer_fingerprint(), old)
        self.assertIn("new", output.lower())
        self.assertIn("retained", output.lower())

        report = verify_receipt(exported)
        self.assertTrue(report["signature_valid"], report)
        detail = next(c["detail"] for c in report["checks"] if c["name"] == "signature_valid")
        self.assertIn("retired", detail)
        self.assertIn(old, detail)

    def test_a_retired_key_never_verifies_a_receipt_it_did_not_sign(self):
        from ramify.crypto import keys
        self.assess(ALLOWED)
        (keys.local_data_store() / "signer_key.json").unlink()
        self._reset()
        forged = dict(self.assess(ALLOWED))
        forged["actor_decision"] = "block"
        self.assertFalse(verify_receipt(forged)["integrity_verified"])


MERRIDALE = "ramify:demo:ppe:merridale-faceshield-std"


class DatasetMutationCase(TempStoreCase):
    """Mutate one field of an in-memory copy of the dataset; artefacts and
    signatures on disk are never touched."""

    def mutated(self, change):
        import copy
        data = copy.deepcopy(seed.seed())
        change(data)
        return patch.object(seed, "seed", return_value=data)

    def posture(self, subject_ref):
        return engine.assess(subject_ref, context="purchase", persist_receipt=False)

    def claim_verdicts(self, subject_ref):
        from ramify.ratify import verify as ratify_verify
        return {c["claim_ref"]: c["verdict"] for c in ratify_verify.claim_results(seed.subject(subject_ref))}


class TestE1DecisionInputsAreBoundToSignedEvidence(DatasetMutationCase):
    """E1: claim value, supported-claim references, record status and valid-from,
    each changed alone with the artefact and signature preserved."""

    def test_genuine_data_still_verifies(self):
        from ramify.ratify import checks
        for ref in seed.subjects():
            for record in checks._evidence_for(seed.subject(ref)):
                with self.subTest(evidence=record["ref"]):
                    self.assertEqual(checks.evaluate_evidence_integrity(record, ref)["state"], "verified")

    def test_revoked_record_cannot_become_acceptable_through_status(self):
        self.assertEqual(self.posture(MERRIDALE)["objective_posture"], "block")
        with self.mutated(lambda d: d["evidence"]["ev:merridale:conformity"].update(record_status="active")):
            result = self.posture(MERRIDALE)
        self.assertEqual(result["objective_posture"], "block")
        self.assertFalse(result["can_add_to_cart"])
        self.assertIn("evidence_artefact_binding_mismatch", result["reason_codes"])

    def test_valid_from_change_is_rejected(self):
        from ramify.ratify import checks
        with self.mutated(lambda d: d["evidence"]["ev:apex:coa"].update(valid_from="2020-01-01T00:00:00.000000000Z")):
            state = checks.evaluate_evidence_integrity(seed.evidence("ev:apex:coa"), ALLOWED)["state"]
            result = self.posture(ALLOWED)
        self.assertEqual(state, "artefact_binding_mismatch")
        self.assertEqual(result["objective_posture"], "block")

    def test_supported_claim_reference_change_is_rejected(self):
        from ramify.ratify import checks
        with self.mutated(lambda d: d["evidence"]["ev:apex:coa"].update(supports_claim_refs=["clm:apex:ingredient"])):
            state = checks.evaluate_evidence_integrity(seed.evidence("ev:apex:coa"), ALLOWED)["state"]
            result = self.posture(ALLOWED)
        self.assertEqual(state, "artefact_binding_mismatch")
        self.assertNotEqual(result["objective_posture"], "allow")

    def test_claim_value_change_is_rejected(self):
        def change(d):
            claim = next(c for c in d["subjects"][ALLOWED]["claims"] if c["ref"] == "clm:apex:ingredient")
            claim["value"] = claim["value"] + " (edited)"
        with self.mutated(change):
            verdicts = self.claim_verdicts(ALLOWED)
            result = self.posture(ALLOWED)
        self.assertNotEqual(verdicts["clm:apex:ingredient"], "accepted")
        self.assertEqual(result["objective_posture"], "block")
        self.assertIn("claim_evidence_binding_invalid", result["reason_codes"])

    def test_pointing_a_claim_at_evidence_for_another_claim_is_rejected(self):
        def change(d):
            claim = next(c for c in d["subjects"][ALLOWED]["claims"] if c["ref"] == "clm:apex:ingredient")
            claim["evidence_refs"] = ["ev:apex:gmp"]
        with self.mutated(change):
            verdicts = self.claim_verdicts(ALLOWED)
            result = self.posture(ALLOWED)
        self.assertNotEqual(verdicts["clm:apex:ingredient"], "accepted")
        self.assertEqual(result["objective_posture"], "block")


class TestE3ClaimVerdictsMatchTheAggregate(DatasetMutationCase):
    """E3: empty, unknown and mismatched references never read as accepted."""

    def _claim(self, d):
        return next(c for c in d["subjects"][ALLOWED]["claims"] if c["ref"] == "clm:apex:ingredient")

    def test_empty_evidence_references(self):
        with self.mutated(lambda d: self._claim(d).update(evidence_refs=[])):
            verdict = self.claim_verdicts(ALLOWED)["clm:apex:ingredient"]
            result = self.posture(ALLOWED)
        self.assertNotIn(verdict, ("accepted", "accepted_with_scope_limit"))
        self.assertEqual(result["objective_posture"], "block")

    def test_unknown_evidence_reference(self):
        with self.mutated(lambda d: self._claim(d).update(evidence_refs=["ev:does-not-exist"])):
            verdict = self.claim_verdicts(ALLOWED)["clm:apex:ingredient"]
        self.assertNotIn(verdict, ("accepted", "accepted_with_scope_limit"))

    def test_evidence_from_another_subject(self):
        with self.mutated(lambda d: self._claim(d).update(evidence_refs=["ev:northbeam:coa"])):
            verdict = self.claim_verdicts(ALLOWED)["clm:apex:ingredient"]
        self.assertNotIn(verdict, ("accepted", "accepted_with_scope_limit"))

    def test_genuine_claims_are_still_accepted(self):
        self.assertTrue(all(v == "accepted" for v in self.claim_verdicts(ALLOWED).values()))


class TestE4CheckSetsAndComparableQuantities(unittest.TestCase):
    """E4: malformed check sets fail closed; omega-3 values compare per serving."""

    def _check(self, check_id, outcome):
        from ramify.ratify.checks import CheckResult
        return CheckResult(check_id, check_id, outcome, "informational", "fixture")

    def test_an_empty_check_list_fails_closed(self):
        from ramify.ratify import precedence
        self.assertEqual(precedence.evaluate([], "no_active_recall").posture, "block")

    def test_an_unknown_outcome_fails_closed(self):
        from ramify.ratify import precedence
        checks = [self._check("identity", "pass"), self._check("standing", "looks_fine")]
        outcome = precedence.evaluate(checks, "no_active_recall")
        self.assertEqual(outcome.posture, "block")
        self.assertIn("check_set_invalid", outcome.reason_codes)

    def test_a_missing_expected_check_fails_closed(self):
        from ramify.ratify import checks as ratify_checks
        from ramify.ratify import precedence
        partial = [self._check(cid, "pass") for cid in ratify_checks.CHECK_IDS[:-1]]
        outcome = precedence.evaluate(partial, "no_active_recall", expected=ratify_checks.CHECK_IDS)
        self.assertEqual(outcome.posture, "block")
        complete = partial + [self._check(ratify_checks.CHECK_IDS[-1], "pass")]
        self.assertEqual(
            precedence.evaluate(complete, "no_active_recall", expected=ratify_checks.CHECK_IDS).posture,
            "allow",
        )

    def test_the_engine_supplies_exactly_the_expected_checks(self):
        from ramify.ratify import checks as ratify_checks
        receipt = engine.assess(ALLOWED, persist_receipt=False)["receipt"]
        self.assertEqual([c["check_id"] for c in receipt["check_results"]], list(ratify_checks.CHECK_IDS))

    def _compare(self, *values):
        from ramify.ratify import checks as ratify_checks
        group = [{"value": v} for v in values]
        return ratify_checks._claim_values_conflict("ingredient_claim", group)[0]

    def test_equivalent_values_on_different_serving_bases_agree(self):
        self.assertEqual(
            self._compare("EPA 180mg / DHA 120mg per softgel", "EPA 360mg / DHA 240mg per 2 softgels"),
            "consistent",
        )

    def test_different_values_on_the_same_basis_conflict(self):
        self.assertEqual(
            self._compare("EPA 180mg / DHA 120mg per softgel", "EPA 300mg / DHA 200mg per softgel"),
            "conflict",
        )

    def test_absent_or_incompatible_denominators_are_not_treated_as_equal(self):
        self.assertEqual(self._compare("EPA 180mg / DHA 120mg per softgel", "EPA 180mg / DHA 120mg"),
                         "incomparable")
        self.assertEqual(self._compare("EPA 180mg / DHA 120mg per softgel", "EPA 180mg / DHA 120mg per 1g oil"),
                         "incomparable")

    def test_the_shipped_omega3_product_keeps_its_verdict(self):
        result = engine.assess("ramify:demo:supp:tidalpoint-omega3-1000-b2025-12-D", persist_receipt=False)
        self.assertEqual(result["objective_posture"], "allow_with_warning")


class TestI1StrictQuantitiesAndHonestBudgetReasons(TempStoreCase):
    """I1: one quantity contract at both boundaries; a missing price is not
    reported as being over budget."""

    BAD = ["5", 5.0, True, 1.5, 0, -1, 1001, None]

    def test_http_rejects_anything_but_a_whole_number_in_range(self):
        for endpoint, body in (("/api/v0/assess", {"identifier": ALLOWED}),
                               ("/api/v0/compare", {"identifier": ALLOWED}),
                               ("/api/v0/alternatives", {"identifier": ALLOWED})):
            for quantity in self.BAD:
                with self.subTest(endpoint=endpoint, quantity=quantity):
                    response = client.post(endpoint, json={**body, "quantity": quantity})
                    self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(client.post(endpoint, json={**body, "quantity": 2}).status_code, 200)

    def test_the_engine_applies_the_same_contract(self):
        for quantity in self.BAD:
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    engine.assess(ALLOWED, quantity=quantity, persist_receipt=False)

    def test_profile_spend_ceilings_must_be_whole_cents(self):
        from ramify.policy import profiles
        for budget in ("500", True, 5.5):
            with self.subTest(budget=budget):
                response = client.post("/api/v0/agents", json={"label": f"Ceiling {budget!r}",
                                                               "budget_limit_cents": budget})
                self.assertEqual(response.status_code, 422, response.text)
                with self.assertRaises(profiles.InvalidProfile):
                    profiles._validate({"label": "x", "budget_limit_cents": budget})

    def test_a_missing_price_is_explained_as_a_missing_price(self):
        from ramify.agent import explain
        with patch.object(seed, "price_cents", return_value=None):
            receipt = engine.assess(ALLOWED, "budget_guard_v1", persist_receipt=False)["receipt"]
        self.assertEqual(receipt["actor_decision"], "hold")
        summary = explain.deterministic_summary(receipt)
        self.assertIn("no price", summary)
        self.assertNotIn("over the", summary)

    def test_an_over_budget_line_is_explained_as_over_budget(self):
        from ramify.agent import explain
        receipt = engine.assess(ALLOWED, "budget_guard_v1", quantity=1000, persist_receipt=False)["receipt"]
        self.assertEqual(receipt["actor_decision"], "hold")
        summary = explain.deterministic_summary(receipt)
        self.assertIn("over the agent's spend ceiling", summary)
        self.assertNotIn("no price", summary)


class _FakeModel:
    name = "fake-model"

    def __init__(self, text):
        self.text = text

    def explain(self, receipt):
        return self.text


class TestL2ExplanationsCannotContradictTheDecision(TempStoreCase):
    """L2: contradictory model prose is replaced; the authoritative summary and
    the signed payload are unchanged."""

    APPROVING = "Good news: this product is safe to buy, so go ahead and purchase it."

    def _explain(self, receipt, model_text):
        with patch("ramify.agent.explain._configured_adapter", return_value=_FakeModel(model_text)):
            response = client.post("/api/v0/explain", json={"receipt": receipt})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_approval_text_for_a_blocked_receipt_is_replaced(self):
        from ramify.agent import explain
        receipt = self.assess(BLOCKED)
        body = self._explain(receipt, self.APPROVING)
        self.assertNotIn("safe to buy", body["explanation"])
        self.assertEqual(body["explanation"], explain.deterministic_summary(receipt))
        self.assertIn("rejected", body["source"])
        self.assertEqual(body["decision_summary"], explain.deterministic_summary(receipt))

    def test_approval_text_for_a_held_receipt_is_replaced(self):
        receipt = self.assess(HELD)
        body = self._explain(receipt, self.APPROVING)
        self.assertNotIn("go ahead", body["explanation"])

    def test_blocking_text_for_an_allowed_receipt_is_replaced(self):
        receipt = self.assess(ALLOWED)
        body = self._explain(receipt, "This product has been recalled. Do not buy it.")
        self.assertNotIn("recalled", body["explanation"])

    def test_consistent_model_text_is_kept(self):
        receipt = self.assess(BLOCKED)
        text = "The batch is under an active recall, so the agent stops here."
        body = self._explain(receipt, text)
        self.assertEqual(body["explanation"], text)
        self.assertEqual(body["source"], "fake-model")

    def test_the_signed_payload_is_unchanged(self):
        receipt = self.assess(BLOCKED)
        before = receipt["payload_hash"]
        self._explain(receipt, self.APPROVING)
        self.assertEqual(receipt["payload_hash"], before)
        self.assertTrue(verify_receipt(receipt)["integrity_verified"])


class TestL1PydanticAdapterUsesTheCheckedEndpoint(unittest.TestCase):
    """L1: the validated URL reaches the provider; malformed output is controlled."""

    def _fake_pydantic_ai(self, captured):
        import sys
        from types import ModuleType

        def module(name, **attrs):
            m = ModuleType(name)
            m.__dict__.update(attrs)
            return m

        class Provider:
            def __init__(self, **kwargs):
                captured["provider"] = kwargs

        class ChatModel:
            def __init__(self, name, provider=None):
                captured["model"] = (name, provider)

        def agent(model, **kwargs):
            captured["agent_model"] = model
            return object()

        return patch.dict(sys.modules, {
            "pydantic_ai": module("pydantic_ai", Agent=agent),
            "pydantic_ai.providers": module("pydantic_ai.providers"),
            "pydantic_ai.providers.openai": module("pydantic_ai.providers.openai", OpenAIProvider=Provider),
            "pydantic_ai.models": module("pydantic_ai.models"),
            "pydantic_ai.models.openai": module("pydantic_ai.models.openai", OpenAIChatModel=ChatModel),
        })

    def test_the_validated_url_reaches_the_provider(self):
        from ramify.agent.pydanticai_adapter import PydanticAIAdapter
        captured = {}
        with self._fake_pydantic_ai(captured), patch.dict(os.environ, {
            "RAMIFY_OLLAMA_BASE_URL": "http://127.0.0.1:12345",
            "RAMIFY_PYDANTICAI_MODEL": "ollama:llama3.1",
        }):
            PydanticAIAdapter()._ensure_agent()
        self.assertEqual(captured["provider"]["base_url"], "http://127.0.0.1:12345/v1")
        name, provider = captured["model"]
        self.assertEqual(name, "llama3.1")
        self.assertIsNotNone(provider)
        self.assertIsNot(captured["agent_model"], "ollama:llama3.1",
                         "Agent must receive the bound model, not a string it resolves itself")

    def test_a_disallowed_endpoint_is_never_constructed(self):
        from ramify.agent.pydanticai_adapter import PydanticAIAdapter
        captured = {}
        with self._fake_pydantic_ai(captured), patch.dict(os.environ, {
                "RAMIFY_OLLAMA_BASE_URL": "http://ollama.example.com:11434"}):
            with self.assertRaises(ValueError):
                PydanticAIAdapter()._ensure_agent()
        self.assertNotIn("provider", captured)

    def test_malformed_model_output_gives_a_controlled_failure(self):
        from types import SimpleNamespace
        from ramify.agent.pydanticai_adapter import PydanticAIAdapter
        candidates = [{"subject_ref": ALLOWED}]
        for output in ("[1, 2]", "null", "not json {", '"a string"', '{"identifier": 42}',
                       '{"identifier": "ramify:demo:supp:not-offered"}'):
            with self.subTest(output=output):
                adapter = PydanticAIAdapter()
                adapter._agent = SimpleNamespace(run_sync=lambda prompt, o=output: SimpleNamespace(output=o))
                result = adapter.interpret("magnesium", candidates)
                self.assertIsNone(result.identifier)
                self.assertEqual(result.confidence, 0.0)


class TestR2ProofPackIsCompleteAndSelfChecking(TempStoreCase):
    """R2: unchanged pack passes; a changed or missing receipt, bad signature,
    malformed shape, extra file or inconsistent manifest fails clearly."""

    def setUp(self):
        super().setUp()
        import io
        import zipfile
        self.folder = tempfile.TemporaryDirectory()
        self.root = __import__("pathlib").Path(self.folder.name)
        zipfile.ZipFile(io.BytesIO(client.get("/api/v0/proof-pack").content)).extractall(self.root)
        self.receipts = sorted((self.root / "receipts").glob("*.json"))

    def tearDown(self):
        self.folder.cleanup()
        super().tearDown()

    def run_verifier(self):
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location("pack_verifier", self.root / "verify_receipts.py")
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = verifier.main([])
        return code, buffer.getvalue()

    def edit_json(self, path, change):
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_the_unchanged_pack_passes(self):
        code, output = self.run_verifier()
        self.assertEqual(code, 0, output)
        self.assertIn("PASS MANIFEST.json", output)
        passes = [line for line in output.splitlines() if line.startswith("PASS ")]
        self.assertEqual(len(passes), len(self.receipts) + 1, output)

    def test_a_changed_receipt_fails(self):
        self.edit_json(self.receipts[0], lambda r: r.update(actor_decision="allow_everything"))
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)
        self.assertIn("does not match its manifest digest", output)

    def test_a_bad_signature_fails(self):
        self.edit_json(self.receipts[0], lambda r: r.update(signature=r["signature"][::-1]))
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)

    def test_a_missing_expected_receipt_fails(self):
        self.receipts[0].unlink()
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)
        self.assertIn("listed in the manifest but missing", output)

    def test_removing_a_receipt_and_its_manifest_line_fails(self):
        name = "receipts/" + self.receipts[0].name
        self.receipts[0].unlink()

        def drop(m):
            m["files"].pop(name)
            m["expected_receipts"].remove(name)
        self.edit_json(self.root / "MANIFEST.json", drop)
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)
        self.assertIn("signature does not verify", output)

    def test_a_malformed_receipt_shape_fails(self):
        self.receipts[0].write_text("[]", encoding="utf-8")
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)
        self.assertIn("not a JSON object", output)

    def test_an_unlisted_extra_receipt_fails(self):
        (self.root / "receipts" / "extra.json").write_text(self.receipts[0].read_text(encoding="utf-8"),
                                                          encoding="utf-8")
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)
        self.assertIn("not in the manifest", output)

    def test_a_missing_manifest_fails(self):
        (self.root / "MANIFEST.json").unlink()
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)
        self.assertIn("MANIFEST.json is missing", output)

    def test_a_malformed_trust_file_fails(self):
        (self.root / "trust" / "public_keys.json").write_text("[]", encoding="utf-8")
        code, output = self.run_verifier()
        self.assertNotEqual(code, 0)

    def test_the_manifest_records_build_identity_and_fingerprint(self):
        import json
        from ramify.crypto import keys
        manifest = json.loads((self.root / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["signer_key_fingerprint"], keys.signer_fingerprint())
        self.assertEqual(manifest["build"]["dataset_digest"], seed.dataset_digest())
        self.assertIn("version", manifest["build"])
        self.assertEqual(len(manifest["expected_receipts"]), len(self.receipts))

    def test_the_pack_contains_no_private_signing_material(self):
        from ramify.crypto import keys
        private_hex = keys.load_signer_private_key().private_bytes_raw().hex()
        blob = b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file())
        self.assertNotIn(private_hex.encode(), blob)
        self.assertNotIn(b"private_hex", blob)


def _load_script(name):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestR1DemoScriptsAreRealChecks(unittest.TestCase):
    """R1: a failed proof exits nonzero; the smoke check rejects wrong products."""

    def _quiet(self, function, *args):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = function(*args)
        return code, buffer.getvalue()

    def _demo_against_a_data_copy(self, *patches):
        import shutil
        demo = _load_script("david_live_verification_demo")
        with tempfile.TemporaryDirectory() as copy_root, \
                patch.dict(os.environ, {"RAMIFY_DATA_DIR": tempfile.mkdtemp()}):
            target = os.path.join(copy_root, "data")
            shutil.copytree(seed.DATA_DIR, target)
            with patch.object(seed, "DATA_DIR", type(seed.DATA_DIR)(target)):
                import contextlib
                with contextlib.ExitStack() as stack:
                    for p in patches:
                        stack.enter_context(p)
                    return self._quiet(demo.main)

    def test_the_demo_passes_when_every_proof_holds(self):
        code, output = self._demo_against_a_data_copy()
        self.assertEqual(code, 0, output)
        self.assertNotIn("[FAIL]", output)

    def test_a_forced_failed_proof_returns_nonzero(self):
        broken = {"integrity_verified": False, "purchase_authority_valid": False,
                  "verified": False, "checks": []}
        code, output = self._demo_against_a_data_copy(
            patch("ramify.crypto.sign.verify_receipt", return_value=broken))
        self.assertIn("[FAIL]", output)
        self.assertNotEqual(code, 0)

    def test_the_demo_leaves_the_data_dir_setting_as_it_found_it(self):
        before = os.environ.get("RAMIFY_DATA_DIR")
        self._demo_against_a_data_copy()
        self.assertEqual(os.environ.get("RAMIFY_DATA_DIR"), before)

    def _smoke(self, readings):
        smoke = _load_script("live_llm_smoke")
        answers = iter(readings)
        with patch.object(smoke.interpreter, "status", return_value={"local_model_available": True}), \
             patch.object(smoke.interpreter, "interpret", side_effect=lambda *a, **k: next(answers)):
            return self._quiet(smoke.main)

    def test_five_live_no_match_answers_fail_the_smoke_check(self):
        live_nothing = [{"source": "langgraph+ollama:llama3.1", "identifier": None}] * 5
        code, output = self._smoke(live_nothing)
        self.assertNotEqual(code, 0, output)

    def test_wrong_products_fail_the_smoke_check(self):
        smoke = _load_script("live_llm_smoke")
        wrong = [{"source": "langgraph+ollama:llama3.1", "identifier": ALLOWED}] * len(smoke.REQUESTS)
        code, output = self._smoke(wrong)
        self.assertNotEqual(code, 0, output)

    def test_missing_participation_fails_the_smoke_check(self):
        smoke = _load_script("live_llm_smoke")
        fallback = [{"source": "deterministic_catalogue", "identifier": expected}
                    for _, expected in smoke.REQUESTS]
        code, output = self._smoke(fallback)
        self.assertNotEqual(code, 0, output)

    def test_correct_live_answers_pass_the_smoke_check(self):
        smoke = _load_script("live_llm_smoke")
        right = [{"source": "langgraph+ollama:llama3.1", "identifier": expected}
                 for _, expected in smoke.REQUESTS]
        code, output = self._smoke(right)
        self.assertEqual(code, 0, output)


class TestT3ReleaseEvidenceIsReproducible(unittest.TestCase):
    """T3: real SHA and clean state, dirty reported false, missing Git explicit,
    one runner, and the actual totals recorded."""

    PYTEST_OUTPUT = "....\n497 passed, 2 skipped, 1 warning in 29.96s\n"

    def _capture(self, git_answers, test_output=PYTEST_OUTPUT, returncode=0):
        import json
        capture = _load_script("capture_release_evidence")
        calls = []

        def fake_command(*args, **kwargs):
            calls.append(list(args))
            if args[0] == "git":
                answer = git_answers.get(args[1])
                if answer is None:
                    return {"available": False, "command": list(args), "error": "git not installed"}
                return {"available": True, "command": list(args), "returncode": 0,
                        "stdout": answer, "stderr": ""}
            return {"available": True, "command": list(args), "returncode": returncode,
                    "stdout": test_output, "stderr": ""}

        with tempfile.TemporaryDirectory() as folder:
            out = __import__("pathlib").Path(folder) / "evidence.json"
            with patch.object(capture, "command", side_effect=fake_command), \
                 patch.object(capture, "OUTPUT", out):
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()):
                    code = capture.main()
            return code, json.loads(out.read_text(encoding="utf-8")), calls

    CLEAN = {"rev-parse": "0123456789abcdef0123456789abcdef01234567", "show": "2026-09-26T12:00:00+10:00",
             "status": ""}

    def test_a_clean_checkout_records_the_sha_and_clean_true(self):
        _, record, _ = self._capture(self.CLEAN)
        self.assertEqual(record["assessed_commit_sha"], self.CLEAN["rev-parse"])
        self.assertIs(record["working_tree_clean"], True)

    def test_a_dirty_checkout_reports_false(self):
        _, record, _ = self._capture({**self.CLEAN, "status": " M backend/ramify/engine.py"})
        self.assertIs(record["working_tree_clean"], False)

    def test_missing_git_metadata_stays_explicit(self):
        _, record, _ = self._capture({})
        self.assertFalse(record["git_metadata_available"])
        self.assertIsNone(record["assessed_commit_sha"])
        self.assertIsNone(record["working_tree_clean"])

    def test_the_full_run_uses_pytest_and_records_totals(self):
        code, record, calls = self._capture(self.CLEAN)
        test_call = next(c for c in calls if c[0] != "git")
        self.assertIn("pytest", test_call)
        self.assertIn("backend/tests", test_call)
        self.assertEqual(record["test_totals"], {"passed": 497, "skipped": 2, "warnings": 1})
        self.assertEqual(code, 0)
        self.assertIn("python", record["environment"])

    def test_a_failing_run_is_recorded_and_exits_nonzero(self):
        code, record, _ = self._capture(self.CLEAN, "1 failed, 496 passed in 30.00s\n", returncode=1)
        self.assertEqual(record["test_totals"]["failed"], 1)
        self.assertNotEqual(code, 0)


class TestU2DemonstrationsUseIsolatedState(TempStoreCase):
    """U2: the tamper demonstration never writes shipped evidence. Concurrent
    isolation is exercised in test_backend_audit_26_sep_2026 (L2)."""

    def test_the_tamper_demo_never_writes_a_shipped_artefact(self):
        from pathlib import Path
        writes = []
        real_write = Path.write_bytes
        shipped_root = seed.DATA_DIR.resolve()

        def watching_write(path, data):
            if shipped_root in Path(path).resolve().parents:
                writes.append(str(path))
            return real_write(path, data)

        with patch.object(Path, "write_bytes", watching_write):
            response = client.post("/api/v0/demo/evidence-tamper", json={"subject_ref": ALLOWED})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(writes, [], "the demonstration wrote to shipped evidence")
        self.assertEqual(response.json()["tampered_integrity"]["state"], "hash_mismatch")
        self.assertEqual(response.json()["objective_posture"], "block")


class TestM1HistoryIsCompleteAndVerifiedOnce(TempStoreCase):
    """M1: no 1,000-event cutoff; ledger verification reads receipts once."""

    def test_actions_older_than_1000_events_stay_traceable(self):
        import json
        receipt = self.assess(ALLOWED)
        rows = [{"receipt_ref": receipt["receipt_id"], "action": "add_to_mock_cart", "seq": 0}]
        rows += [{"receipt_ref": f"ramify:demo:rcpt:other{i}", "action": "halt", "seq": i}
                 for i in range(1, 1200)]
        store.action_log_path().write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        found = store.actions_for(receipt["receipt_id"])
        self.assertEqual([e["seq"] for e in found], [0])

    def test_ledger_verification_reads_the_receipt_ledger_once(self):
        receipt = self.assess(ALLOWED)
        for i in range(40):
            store.record_action({"event_id": f"e{i}", "action": "compare_alternatives",
                                 "receipt_ref": receipt["receipt_id"],
                                 "receipt_hash": receipt["payload_hash"]})
        reads = []
        real_read = store.read_jsonl

        def counting(path):
            if path == store.ledger_path():
                reads.append(path)
            return real_read(path)

        with patch.object(store, "read_jsonl", side_effect=counting):
            report = store.verify_action_ledger()
        self.assertTrue(report["valid"], report["problems"][:3])
        self.assertEqual(report["total"], 40)
        self.assertLessEqual(len(reads), 1, f"receipt ledger read {len(reads)} times for 40 actions")


if __name__ == "__main__":
    unittest.main()

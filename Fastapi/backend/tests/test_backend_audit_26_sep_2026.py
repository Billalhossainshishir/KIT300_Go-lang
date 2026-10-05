"""Regressions for the findings of the 26 September 2026 backend audit.

Each class reproduces one finding and fails against the code before its fix.
Every case runs against a throwaway ``RAMIFY_DATA_DIR`` so the demonstration
ledger and the signed evidence artefacts are never touched.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ramify.api.app import app
from ramify.data import seed

client = TestClient(app)

HELD = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"
ALLOWED = "ramify:demo:supp:apex-mg-glyc-120"


class TempStoreCase(unittest.TestCase):
    """Isolate the receipt ledger, basket, profiles and signer."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"RAMIFY_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def assess(self, subject_ref, actor_ref="consumer_v1"):
        response = client.post("/api/v0/assess", json={
            "identifier": subject_ref,
            "actor_ref": actor_ref,
            "quantity": 1,
            "context": "purchase",
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["receipt"]

    def review(self, receipt_id, outcome="overridden"):
        return client.post("/api/v0/receipt/review", json={
            "receipt_id": receipt_id,
            "outcome": outcome,
        })


class TestN5VerifyRejectsUnknownPolicyCleanly(TempStoreCase):
    """An unknown policy is a client error, never a server crash."""

    def test_unknown_policy_is_a_400_not_a_500(self):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/v0/verify", json={"subject_ref": ALLOWED, "policy_ref": "bogus"}
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Unknown policy reference", response.json()["detail"])

    def test_the_evaluated_policy_is_still_accepted(self):
        pack = seed.policy_pack()
        response = client.post(
            "/api/v0/verify", json={"subject_ref": ALLOWED, "policy_ref": pack["policy_ref"]}
        )
        self.assertEqual(response.status_code, 200, response.text)


class TestN3ReviewUsesTheSealedPurchaseStyle(TempStoreCase):
    """A procurement decision stays a requisition whatever happens to the profile."""

    def _editable(self, ref):
        from ramify.policy import profiles
        return {k: profiles.profile(ref)[k] for k in profiles.EDITABLE_FIELDS}

    def test_the_receipt_seals_the_purchase_style(self):
        self.assertEqual(self.assess(HELD, "procurement_v1")["actor_purchase_style"], "requisition")
        self.assertEqual(self.assess(HELD, "consumer_v1")["actor_purchase_style"], "cart")

    def test_editing_the_profile_before_review_does_not_change_the_grant(self):
        receipt = self.assess(HELD, "procurement_v1")
        body = self._editable("procurement_v1")
        body["purchase_style"] = "cart"
        self.assertEqual(client.put("/api/v0/agents/procurement_v1", json=body).status_code, 200)

        response = self.review(receipt["receipt_id"])
        self.assertEqual(response.status_code, 200, response.text)
        successor = response.json()["receipt"]
        self.assertEqual(successor["human_authorised_actions"], ["create_mock_requisition"])

        add = client.post("/api/v0/cart/add", json={"receipt_ref": successor["receipt_id"]})
        self.assertEqual(add.status_code, 409, add.text)

    def test_deleting_a_requisition_agent_does_not_turn_it_into_a_cart(self):
        created = client.post("/api/v0/agents", json={
            "label": "Ward procurement", "purchase_style": "requisition",
        }).json()["ref"]
        receipt = self.assess(HELD, created)
        self.assertEqual(client.delete(f"/api/v0/agents/{created}").status_code, 200)

        successor = self.review(receipt["receipt_id"]).json()["receipt"]
        self.assertEqual(successor["human_authorised_actions"], ["create_mock_requisition"])

    def test_a_receipt_without_a_sealed_style_is_not_granted_anything(self):
        from ramify.crypto.sign import seal
        from ramify.receipt import store

        receipt = self.assess(HELD)
        legacy = {k: v for k, v in receipt.items()
                  if k not in ("payload_hash", "signature", "actor_purchase_style")}
        legacy["receipt_id"] = receipt["receipt_id"] + "-legacy"
        store.append(seal(legacy))

        response = self.review(legacy["receipt_id"])
        self.assertEqual(response.status_code, 409, response.text)


class TestL3CrossSiteWritesAndForeignHostsAreRefused(TempStoreCase):
    """A page on another site must not change local state, and a rebound
    hostname must not reach the API at all."""

    FOREIGN = {"Origin": "https://evil.example"}

    def test_a_cross_site_form_post_cannot_reset_the_basket(self):
        response = client.post(
            "/api/v0/demo/cart/reset",
            headers={**self.FOREIGN, "Content-Type": "application/x-www-form-urlencoded"},
            content=b"",
        )
        self.assertEqual(response.status_code, 403, response.text)

    def test_a_cross_site_request_cannot_check_out_or_delete(self):
        self.assertEqual(client.post("/api/v0/cart/checkout", headers=self.FOREIGN).status_code, 403)
        self.assertEqual(client.delete("/api/v0/cart", headers=self.FOREIGN).status_code, 403)

    def test_a_null_origin_is_refused(self):
        response = client.post("/api/v0/demo/cart/reset", headers={"Origin": "null"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_same_origin_and_originless_writes_still_work(self):
        same = client.post("/api/v0/demo/cart/reset", headers={"Origin": "http://testserver"})
        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual(client.post("/api/v0/demo/cart/reset").status_code, 200)

    def test_a_foreign_host_header_is_refused(self):
        response = client.get("/healthz", headers={"Host": "attacker.example"})
        self.assertEqual(response.status_code, 400, response.text)

    def test_loopback_host_headers_are_accepted(self):
        for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000"):
            with self.subTest(host=host):
                self.assertEqual(client.get("/healthz", headers={"Host": host}).status_code, 200)

    def test_reads_from_the_page_itself_are_unaffected(self):
        response = client.get("/api/v0/cart", headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200)


class TestN2ReviewDoesNotOverstateWhoApproved(TempStoreCase):
    """No caller is authenticated, so the sealed record must not claim one was."""

    def test_the_successor_records_that_identity_was_not_verified(self):
        receipt = self.assess(HELD)
        successor = self.review(receipt["receipt_id"]).json()["receipt"]
        review = successor["human_review"]
        self.assertIs(review["identity_verified"], False)
        self.assertIn("not authenticated", review["reviewer_attestation"])
        self.assertNotIn("The named reviewer made this", review["reviewer_attestation"])
        self.assertIs(successor["human_receipt"]["reviewer"]["identity_verified"], False)


class TestN8CustomAgentsCannotBorrowAShippedName(TempStoreCase):
    """The readable name in a sealed receipt must identify the agent."""

    SHIPPED = "Consumer shopping agent"

    def test_creating_an_agent_with_a_shipped_name_is_refused(self):
        for label in (self.SHIPPED, "  consumer SHOPPING agent "):
            with self.subTest(label=label):
                response = client.post("/api/v0/agents", json={"label": label})
                self.assertEqual(response.status_code, 400, response.text)

    def test_renaming_a_custom_agent_to_a_shipped_name_is_refused(self):
        from ramify.policy import profiles
        ref = client.post("/api/v0/agents", json={"label": "My helper"}).json()["ref"]
        body = {k: profiles.profile(ref)[k] for k in profiles.EDITABLE_FIELDS}
        body["label"] = self.SHIPPED
        self.assertEqual(client.put(f"/api/v0/agents/{ref}", json=body).status_code, 400)

    def test_a_shipped_agent_can_keep_its_own_name(self):
        from ramify.policy import profiles
        body = {k: profiles.profile("consumer_v1")[k] for k in profiles.EDITABLE_FIELDS}
        body["budget_limit_cents"] = 5000
        self.assertEqual(client.put("/api/v0/agents/consumer_v1", json=body).status_code, 200)

    def test_a_shipped_agent_cannot_take_another_shipped_name(self):
        from ramify.policy import profiles
        body = {k: profiles.profile("procurement_v1")[k] for k in profiles.EDITABLE_FIELDS}
        body["label"] = self.SHIPPED
        self.assertEqual(client.put("/api/v0/agents/procurement_v1", json=body).status_code, 400)


class TestN7ParitySwitchNeverServesRequests(TempStoreCase):
    """With a pinned receipt ID every receipt collides, so HTTP must refuse."""

    def test_the_api_refuses_to_serve_in_deterministic_mode(self):
        with patch.dict(os.environ, {"RAMIFY_DEMO_DETERMINISTIC": "1"}):
            self.assertEqual(client.get("/healthz").status_code, 503)
            response = client.post("/api/v0/assess", json={"identifier": ALLOWED})
            self.assertEqual(response.status_code, 503, response.text)

    def test_the_engine_can_still_run_deterministically_for_parity(self):
        from ramify import engine
        with patch.dict(os.environ, {"RAMIFY_DEMO_DETERMINISTIC": "1"}):
            first = engine.assess(ALLOWED, persist_receipt=False)["receipt"]["payload_hash"]
            second = engine.assess(ALLOWED, persist_receipt=False)["receipt"]["payload_hash"]
        self.assertEqual(first, second)

    def test_normal_mode_serves(self):
        self.assertEqual(client.get("/healthz").status_code, 200)


class TestL2TamperDemoDoesNotLeakIntoOtherAssessments(TempStoreCase):
    """While the demonstration has an artefact modified, nobody else reads it.

    Runs against a temporary copy of the data directory, so the shipped
    signed artefacts are never written by this test.
    """

    SUBJECT = "ramify:demo:supp:apex-mg-glyc-120"

    def setUp(self):
        super().setUp()
        import shutil
        self.data_copy = tempfile.TemporaryDirectory()
        target = os.path.join(self.data_copy.name, "data")
        shutil.copytree(seed.DATA_DIR, target)
        self.data_patch = patch.object(seed, "DATA_DIR", type(seed.DATA_DIR)(target))
        self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop()
        self.data_copy.cleanup()
        super().tearDown()

    def test_a_concurrent_integrity_check_waits_for_the_restore(self):
        import threading
        from ramify import engine as engine_module
        from ramify.ratify import checks

        record = next(r for r in checks._evidence_for(seed.subject(self.SUBJECT))
                      if r.get("storage_path"))
        in_window, release = threading.Event(), threading.Event()
        real_assess = engine_module.assess

        def paused_assess(*args, **kwargs):
            in_window.set()
            release.wait(timeout=10)
            return real_assess(*args, **kwargs)

        demo_result = {}
        with patch("ramify.api.app.engine.assess", side_effect=paused_assess):
            demo = threading.Thread(target=lambda: demo_result.update(
                response=client.post("/api/v0/demo/evidence-tamper",
                                     json={"subject_ref": self.SUBJECT})))
            demo.start()
            self.assertTrue(in_window.wait(timeout=10), "demo never reached its window")

            # Inside the window: a concurrent check must see clean evidence, and
            # the shipped file must be byte-identical. (Updated for David's U2:
            # the demonstration now tampers an isolated copy, so the reader
            # never has to wait for a restore.)
            shipped = (seed.DATA_DIR / record["storage_path"])
            original = shipped.read_bytes()
            observed = {}
            reader = threading.Thread(target=lambda: observed.update(
                state=checks.evaluate_evidence_integrity(record, self.SUBJECT)["state"]))
            reader.start()
            reader.join(timeout=10)
            state_inside_window = observed.get("state")
            shipped_unchanged_inside_window = shipped.read_bytes() == original

            release.set()
            demo.join(timeout=20)

        self.assertEqual(state_inside_window, "verified",
                         "an ordinary check observed demonstration-only tampering")
        self.assertTrue(shipped_unchanged_inside_window, "the shipped artefact was written during the demo")
        body = demo_result["response"].json()
        self.assertEqual(demo_result["response"].status_code, 200)
        self.assertEqual(body["tampered_integrity"]["state"], "hash_mismatch")
        self.assertTrue(body["isolated_copy"])
        self.assertTrue(body["artefact_restored"])


class TestN6ResetReportsWhatHappenedToTheKey(TempStoreCase):
    """A reset without seed material mints a new signer and must say so."""

    def _run_reset(self):
        import contextlib
        import importlib.util
        import io
        from pathlib import Path

        script = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"
        spec = importlib.util.spec_from_file_location("ramify_seed_script", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            module.do_reset()
        return buffer.getvalue()

    def test_the_message_matches_what_happened_to_the_key(self):
        # Reset now keeps the signer (David's K1), so "Keys unchanged" is true
        # when a key is present and must not be printed when one was minted.
        from ramify.crypto import keys
        self.assertFalse((keys.SEED_PRIVATE_DIR / "keys.json").exists(), "fixture expects no seed material")

        self.assess(ALLOWED)
        before = keys.signer_fingerprint()
        output = self._run_reset()
        self.assertEqual(keys.signer_fingerprint(), before)
        self.assertIn("Keys unchanged", output)

        (keys.local_data_store() / "signer_key.json").unlink()
        output = self._run_reset()
        self.assertNotEqual(keys.signer_fingerprint(), before)
        self.assertNotIn("Keys unchanged", output)
        self.assertIn("new one was generated", output)


def _portable_verifier():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "portable_verify.py"
    spec = importlib.util.spec_from_file_location("ramify_portable_verify", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestN10PortableVerifierFailsCleanly(unittest.TestCase):
    """Malformed input is a failed verification, never a crash."""

    def test_non_object_receipts_fail_without_raising(self):
        from pathlib import Path
        verifier = _portable_verifier()
        with tempfile.TemporaryDirectory() as folder:
            for name, body in (("array.json", "[1, 2, 3]"), ("string.json", '"receipt"'),
                               ("number.json", "42"), ("null.json", "null")):
                with self.subTest(body=body):
                    path = Path(folder) / name
                    path.write_text(body, encoding="utf-8")
                    ok, detail = verifier.verify(path, {})
                    self.assertFalse(ok)
                    self.assertIn("object", detail)


class TestN1SignerKeyIsVisible(TempStoreCase):
    """A proof pack carries its own key, so the key must be shown to be checked."""

    def _expected(self):
        import hashlib
        from ramify.crypto import keys
        raw = keys.load_signer_private_key().public_key().public_bytes_raw()
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def test_verification_reports_the_signer_fingerprint(self):
        receipt = self.assess(ALLOWED)
        report = client.post("/api/v0/receipt/verify", json=receipt).json()
        self.assertEqual(report["signer_key_fingerprint"], self._expected())

    def test_the_running_instance_publishes_the_same_fingerprint(self):
        self.assess(ALLOWED)
        self.assertEqual(client.get("/healthz").json()["signer_key_fingerprint"], self._expected())

    def test_the_proof_pack_names_its_key_and_says_it_cannot_vouch_for_it(self):
        import io
        import zipfile
        pack = zipfile.ZipFile(io.BytesIO(client.get("/api/v0/proof-pack").content))
        readme = pack.read("README.txt").decode("utf-8")
        self.assertIn(self._expected(), readme)
        self.assertIn("cannot vouch for its own key", readme)

    def test_the_portable_verifier_prints_the_fingerprint(self):
        import contextlib
        import io
        import json
        import zipfile
        from pathlib import Path

        verifier = _portable_verifier()
        pack = zipfile.ZipFile(io.BytesIO(client.get("/api/v0/proof-pack").content))
        with tempfile.TemporaryDirectory() as folder:
            pack.extractall(folder)
            verifier.ROOT = Path(folder)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = verifier.main([])
        output = buffer.getvalue()
        self.assertEqual(code, 0, output)
        self.assertIn(self._expected(), output)
        self.assertIn("compare", output.lower())


class TestN4RecallAndSellerRecordsAreSigned(TempStoreCase):
    """N4: the recall standing and seller authority that decide a verdict are
    authenticated like evidence. Mutations are in-memory copies only."""

    BLOCKED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
    ADVISORY = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"
    UNVERIFIED_SELLER_PRODUCT = None  # found in setUp

    def mutated(self, change):
        import copy
        data = copy.deepcopy(seed.seed())
        change(data)
        return patch.object(seed, "seed", return_value=data)

    def posture(self, ref):
        from ramify import engine
        return engine.assess(ref, context="purchase", persist_receipt=False)

    def test_every_shipped_record_verifies(self):
        from ramify.ratify import checks
        for ref, record in seed.seed()["statuses"].items():
            with self.subTest(status=ref):
                self.assertEqual(checks.evaluate_record_integrity("statuses", ref, record)["state"], "verified")
        for ref, record in seed.seed()["sellers"].items():
            with self.subTest(seller=ref):
                self.assertEqual(checks.evaluate_record_integrity("sellers", ref, record)["state"], "verified")

    def test_clearing_a_recall_does_not_clear_the_block(self):
        self.assertEqual(self.posture(self.BLOCKED)["objective_posture"], "block")
        with self.mutated(lambda d: d["statuses"][self.BLOCKED].update(standing="no_active_recall")):
            result = self.posture(self.BLOCKED)
        self.assertEqual(result["objective_posture"], "block")
        self.assertFalse(result["can_add_to_cart"])
        self.assertIn("status_record_integrity_failed", result["reason_codes"])

    def test_clearing_an_advisory_does_not_allow_the_product(self):
        with self.mutated(lambda d: d["statuses"][self.ADVISORY].update(standing="no_active_recall")):
            result = self.posture(self.ADVISORY)
        self.assertEqual(result["objective_posture"], "block")

    def test_upgrading_a_seller_does_not_improve_the_verdict(self):
        seller_ref = next(r for r, s in seed.seed()["sellers"].items() if s["authority"] == "unverified")
        product = next(r for r, s in seed.subjects().items() if s["seller_ref"] == seller_ref)
        before = self.posture(product)["objective_posture"]
        with self.mutated(lambda d: d["sellers"][seller_ref].update(authority="verified")):
            after = self.posture(product)
        self.assertEqual(after["objective_posture"], "block", f"was {before}")
        self.assertIn("seller_record_integrity_failed", after["reason_codes"])

    def test_widening_a_sellers_categories_is_caught(self):
        from ramify.ratify import checks
        ref = next(iter(seed.seed()["sellers"]))
        with self.mutated(lambda d: d["sellers"][ref]["authorised_categories"].append("pharmaceutical")):
            state = checks.evaluate_record_integrity("sellers", ref, seed.seller(ref))["state"]
        self.assertEqual(state, "hash_mismatch")

    def test_an_unsigned_status_record_escalates_rather_than_allows(self):
        allowed = "ramify:demo:supp:apex-mg-glyc-120"
        empty = patch.object(seed, "record_signatures", return_value={"statuses": {}, "sellers":
                             seed.record_signatures()["sellers"]})
        with empty:
            result = self.posture(allowed)
        self.assertEqual(result["objective_posture"], "escalate")
        self.assertIn("status_record_unsigned", result["reason_codes"])

    def test_the_receipt_records_status_integrity(self):
        from ramify import engine
        receipt = engine.assess(self.BLOCKED, persist_receipt=False)["receipt"]
        self.assertEqual(receipt["status_result"]["integrity"], "verified")


if __name__ == "__main__":
    unittest.main()

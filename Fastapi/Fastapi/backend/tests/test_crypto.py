"""Canonicalisation, sealing and verification.

The canonicalisation tests come first because everything else rests on them. If
the signer and the verifier disagree by one byte, every receipt in the system
fails and no other test result means anything.
"""

import copy
import json
import unittest

from ramify.crypto.canonical import canonicalise_receipt, rfc3339_nano
from ramify.crypto.sign import payload_hash, seal, verify_receipt
from ramify.engine import assess


class TestCanonicalForm(unittest.TestCase):
    def test_keys_are_sorted_and_whitespace_removed(self):
        canonical = canonicalise_receipt({"b": 1, "a": 2, "c": {"z": 1, "y": 2}})
        self.assertEqual(canonical, b'{"a":2,"b":1,"c":{"y":2,"z":1}}')

    def test_hash_and_signature_are_excluded(self):
        base = {"subject_ref": "x", "latencies_us": {"total": 5}}
        sealed = dict(base, payload_hash="sha256:deadbeef", signature="abc")
        self.assertEqual(canonicalise_receipt(base), canonicalise_receipt(sealed))

    def test_empty_collections_survive_as_themselves(self):
        canonical = canonicalise_receipt({"codes": [], "map": {}})
        self.assertEqual(canonical, b'{"codes":[],"map":{}}')
        self.assertNotIn(b"null", canonical)

    def test_null_is_distinguishable_from_absent(self):
        # The Sprint 1 canonicaliser dropped None at hash time, so a receipt
        # with `reason: null` hashed identically to one with no reason field at
        # all. That let a field be removed without detection.
        with_null = canonicalise_receipt({"a": 1, "reason": None})
        without = canonicalise_receipt({"a": 1})
        self.assertNotEqual(with_null, without)

    def test_floats_are_refused(self):
        with self.assertRaises(ValueError) as caught:
            canonicalise_receipt({"latencies_us": {"total": 1.5}})
        self.assertIn("integer microseconds", str(caught.exception))

    def test_nested_floats_are_refused(self):
        with self.assertRaises(ValueError):
            canonicalise_receipt({"trace": [{"latency_us": 2.0}]})

    def test_timestamps_carry_the_mandatory_z(self):
        stamp = rfc3339_nano()
        self.assertTrue(stamp.endswith("Z"))
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z$")

    def test_unicode_is_not_escaped_away(self):
        canonical = canonicalise_receipt({"detail": "125µg per softgel"})
        self.assertIn("µ".encode("utf-8"), canonical)


class TestSealing(unittest.TestCase):
    def test_a_fresh_receipt_verifies(self):
        # The positive control. The Sprint 1 build failed this one because it
        # wrote the total latency into the receipt after hashing it.
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        report = verify_receipt(receipt)
        self.assertTrue(report["verified"], report["checks"])
        for check in report["checks"]:
            self.assertTrue(check["passed"], f"{check['name']}: {check['detail']}")

    def test_every_scenario_produces_a_verifying_receipt(self):
        from ramify.data import seed

        for scenario in seed.scenarios():
            with self.subTest(scenario=scenario["id"]):
                receipt = assess(scenario["subject_ref"], scenario["actor"])["receipt"]
                self.assertTrue(verify_receipt(receipt)["verified"])

    def test_altering_the_decision_is_detected(self):
        receipt = assess("ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z")["receipt"]
        tampered = copy.deepcopy(receipt)
        tampered["actor_decision"] = "allow"
        report = verify_receipt(tampered)
        self.assertFalse(report["verified"])
        self.assertFalse(report["hash_valid"])
        self.assertFalse(report["signature_valid"])

    def test_altering_one_character_of_prose_is_detected(self):
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        tampered = copy.deepcopy(receipt)
        tampered["notice"] = receipt["notice"].replace("Synthetic", "Authentic")
        self.assertFalse(verify_receipt(tampered)["verified"])

    def test_removing_a_field_is_detected(self):
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        tampered = copy.deepcopy(receipt)
        del tampered["reason_codes"]
        self.assertFalse(verify_receipt(tampered)["verified"])

    def test_replacing_the_signature_is_detected(self):
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        tampered = copy.deepcopy(receipt)
        tampered["signature"] = "A" * 88
        report = verify_receipt(tampered)
        self.assertTrue(report["hash_valid"])
        self.assertFalse(report["signature_valid"])

    def test_an_unknown_issuer_fails_the_chain_check(self):
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        tampered = copy.deepcopy(receipt)
        tampered["issuer_refs"] = ["ramify:demo:issuer:Invented_Authority"]
        report = verify_receipt(tampered)
        self.assertFalse(report["issuer_refs_known"])

    def test_an_escalate_receipt_may_cite_no_issuers(self):
        # An unknown product genuinely has nobody asserting anything about it.
        # Failing the chain check on that basis would punish the system for
        # being honest that it could not find the product.
        receipt = assess("not-a-real-product")["receipt"]
        self.assertEqual(receipt["objective_posture"], "escalate")
        self.assertEqual(receipt["issuer_refs"], [])
        self.assertTrue(verify_receipt(receipt)["verified"])

    def test_a_concluding_receipt_may_not_cite_no_issuers(self):
        # Reaching allow while naming nobody who vouched for anything is
        # internally inconsistent, whatever the signature says.
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        tampered = copy.deepcopy(receipt)
        tampered["issuer_refs"] = []
        report = verify_receipt(tampered)
        self.assertFalse(report["issuer_refs_known"])

    def test_checks_are_reported_independently(self):
        # Sprint 1 returned one boolean under four names while the interface
        # printed "checking issuer chain... valid". Each check must stand alone.
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        tampered = copy.deepcopy(receipt)
        tampered["product_name"] = "Something else"
        report = verify_receipt(tampered)
        self.assertFalse(report["hash_valid"])
        self.assertTrue(report["issuer_refs_known"])
        self.assertTrue(report["scope_valid"])

    def test_sealing_is_reproducible_for_identical_content(self):
        body = {"subject_ref": "x", "reason_codes": [], "latencies_us": {"total": 1}}
        first = seal(copy.deepcopy(body))
        second = seal(copy.deepcopy(body))
        self.assertEqual(first["payload_hash"], second["payload_hash"])
        self.assertEqual(first["payload_hash"], payload_hash(body))

    def test_hash_is_prefixed_hex_of_the_right_length(self):
        receipt = assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        self.assertTrue(receipt["payload_hash"].startswith("sha256:"))
        self.assertEqual(len(receipt["payload_hash"]), len("sha256:") + 64)

    def test_receipt_round_trips_through_json_unchanged(self):
        # A receipt is copied out of the browser and pasted into the CLI. If
        # serialisation altered anything, verification would fail off-machine.
        receipt = assess("ramify:demo:supp:greenline-ashw-ksm66-90")["receipt"]
        round_tripped = json.loads(json.dumps(receipt))
        self.assertTrue(verify_receipt(round_tripped)["verified"])


if __name__ == "__main__":
    unittest.main()

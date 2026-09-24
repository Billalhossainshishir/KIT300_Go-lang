"""Receipt structure, determinism, and the append-only store."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from ramify.crypto.canonical import canonicalise_receipt
from ramify.crypto.sign import verify_receipt
from ramify.data import seed
from ramify.engine import assess
from ramify.receipt import store

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FIELDS = (
    "schema_version",
    "receipt_id",
    "subject_ref",
    "data_snapshot",
    "policy_ref",
    "policy_version",
    "policy_status",
    "actor_ref",
    "call_trace",
    "check_results",
    "claim_results",
    "status_result",
    "objective_posture",
    "matched_conditions",
    "actor_decision",
    "reason_codes",
    "permitted_actions",
    "selected_action",
    "issuer_refs",
    "timestamp",
    "expires_at",
    "latencies_us",
    "payload_hash",
    "signature",
)


class TestReceiptStructure(unittest.TestCase):
    def setUp(self):
        self.receipt = assess("ramify:demo:supp:greenline-ashw-ksm66-90", "procurement_v1")[
            "receipt"
        ]

    def test_every_required_field_is_present(self):
        for field in REQUIRED_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, self.receipt)

    def test_the_traffic_light_is_not_in_the_receipt(self):
        # Client direction of 22 July 2026, item 2: the posture is the decision
        # and the colour is presentation, derived at the display layer.
        self.assertNotIn("traffic_light", self.receipt)

    def test_both_postures_are_recorded(self):
        # Without both, the proof case cannot be demonstrated from the receipt.
        self.assertIn("objective_posture", self.receipt)
        self.assertIn("actor_decision", self.receipt)
        self.assertEqual(self.receipt["objective_posture"], "allow_with_warning")
        self.assertEqual(self.receipt["actor_decision"], "hold")

    def test_reasoning_is_carried_not_just_the_conclusion(self):
        self.assertEqual(len(self.receipt["check_results"]), 7)
        for check in self.receipt["check_results"]:
            self.assertIn("detail", check)
            self.assertIn("evidence_consulted", check)

    def test_data_freshness_is_recorded(self):
        self.assertEqual(self.receipt["data_snapshot"], seed.snapshot_id())
        self.assertTrue(self.receipt["expires_at"] > self.receipt["timestamp"])

    def test_latencies_are_integer_microseconds(self):
        for stage, value in self.receipt["latencies_us"].items():
            with self.subTest(stage=stage):
                self.assertIsInstance(value, int)
                self.assertNotIsInstance(value, bool)

    def test_the_total_latency_is_inside_the_signed_payload(self):
        # The Sprint 1 defect: `total` was written in after the hash was
        # computed, so no receipt ever verified.
        self.assertIn("total", self.receipt["latencies_us"])
        self.assertTrue(verify_receipt(self.receipt)["verified"])

    def test_no_float_survives_into_the_canonical_form(self):
        canonical = json.loads(canonicalise_receipt(self.receipt))

        def walk(node, path="receipt"):
            if isinstance(node, float):
                self.fail(f"float at {path}")
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        walk(canonical)

    def test_the_policy_pack_is_labelled_a_demonstration_set(self):
        # Client direction item 3: the pack must never be represented as
        # production rules.
        self.assertEqual(self.receipt["policy_status"], "demonstration_only")
        self.assertTrue(self.receipt["policy_version"])

    def test_the_synthetic_notice_travels_with_the_receipt(self):
        self.assertIn("Synthetic", self.receipt["notice"])


class TestDeterministicMode(unittest.TestCase):
    """Amendment v0.4.1 item 3.

    Live receipts carry live timestamps and real latencies, so two machines
    cannot produce identical hashes. The flag exists so parity can be tested
    without pinning the live demonstration.
    """

    SNIPPET = (
        "import sys; sys.path.insert(0, 'src');"
        "from ramify.engine import assess;"
        "print(assess('ramify:demo:supp:apex-mg-glyc-120')['receipt']['payload_hash'])"
    )

    def _hash_in_subprocess(self, deterministic: bool) -> str:
        env = dict(os.environ)
        if deterministic:
            env["RAMIFY_DEMO_DETERMINISTIC"] = "1"
        else:
            env.pop("RAMIFY_DEMO_DETERMINISTIC", None)
        result = subprocess.run(
            [sys.executable, "-c", self.SNIPPET],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_pinned_runs_are_byte_identical(self):
        self.assertEqual(
            self._hash_in_subprocess(True), self._hash_in_subprocess(True)
        )

    def test_live_runs_differ(self):
        # Otherwise a fixture could leak into a live demonstration unnoticed.
        self.assertNotEqual(
            self._hash_in_subprocess(False), self._hash_in_subprocess(False)
        )


class TestAppendOnlyStore(unittest.TestCase):
    def test_a_receipt_is_persisted(self):
        result = assess("ramify:demo:supp:apex-mg-glyc-120")
        self.assertIsNotNone(store.get(result["receipt_ref"]))

    def test_the_ledger_only_grows(self):
        before = len(store.all_receipts())
        assess("ramify:demo:supp:apex-mg-glyc-120")
        assess("ramify:demo:supp:greenline-ashw-ksm66-90")
        self.assertEqual(len(store.all_receipts()), before + 2)

    def test_stored_receipts_still_verify(self):
        result = assess("ramify:demo:supp:apex-mg-glyc-120")
        stored = store.get(result["receipt_ref"])
        self.assertTrue(verify_receipt(stored)["verified"])


if __name__ == "__main__":
    unittest.main()

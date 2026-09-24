"""Regression coverage for David Male's 26-28 Aug FastAPI feedback."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from ramify import engine
from ramify.action import alternatives
from ramify.api.app import app
from ramify.crypto import keys
from ramify.crypto.sign import payload_digest, payload_hash, verify_receipt
from ramify.data import seed
from ramify.policy import profiles
from ramify.ratify import checks

client = TestClient(app)


class TestEvidenceTrustChain(unittest.TestCase):
    def test_every_shipped_evidence_artefact_verifies(self):
        for ref in seed.seed()["evidence"]:
            record = seed.evidence(ref)
            with self.subTest(evidence=ref):
                self.assertEqual(
                    checks.evaluate_evidence_integrity(record, record["subject_ref"])["state"],
                    "verified",
                )

    def test_brightway_provenance_chronology_is_coherent(self):
        record = seed.evidence("ev:brightway-m:gmp")
        self.assertLessEqual(
            seed.parse_timestamp(record["issued_at"]),
            seed.parse_timestamp(record["retrieved_at"]),
        )
        self.assertEqual(checks.evaluate_evidence_freshness(record, seed.snapshot_date())["state"], "not_yet_valid")

    def test_claim_results_reuse_evidence_validity_logic(self):
        brightway = engine.assess(
            "ramify:demo:supp:brightway-vitd3-5000-b2025-06-M", persist_receipt=False
        )["receipt"]
        cert = next(c for c in brightway["claim_results"] if c["type"] == "certification_claim")
        self.assertEqual(cert["verdict"], "accepted_with_scope_limit")
        self.assertIn("evidence_not_yet_valid", cert["reason_codes"])

        merridale = engine.assess(
            "ramify:demo:ppe:merridale-faceshield-std", persist_receipt=False
        )["receipt"]
        cert = merridale["claim_results"][0]
        self.assertEqual(cert["verdict"], "revoked")
        self.assertIn("evidence_revoked", cert["reason_codes"])


class TestAlternativesBoundary(unittest.TestCase):
    def test_objective_hold_does_not_offer_ordinary_alternatives(self):
        result = engine.assess(
            "ramify:demo:supp:brightway-vitd3-5000-b2025-06-M", persist_receipt=False
        )
        self.assertEqual(result["objective_posture"], "hold")
        self.assertIsNone(
            alternatives.find(result["subject_ref"], result["receipt"]["actor_ref"], 1, result)
        )

    def test_exploratory_alternatives_do_not_return_purchase_receipt_refs(self):
        result = engine.assess(
            "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A",
            "procurement_v1",
            persist_receipt=False,
        )
        self.assertEqual(result["objective_posture"], "allow")
        self.assertEqual(result["actor_decision"], "hold")
        suggestions = alternatives.find(result["subject_ref"], result["receipt"]["actor_ref"], 1, result)
        if suggestions:
            for candidate in suggestions["candidates"]:
                self.assertNotIn("receipt_ref", candidate)
                self.assertEqual(candidate["assessment_context"], "exploratory")


class TestPolicyAndProfiles(unittest.TestCase):
    def test_policy_pack_describes_real_precedence_algorithm(self):
        note = seed.policy_pack()["precedence"]["note"].lower()
        self.assertNotIn("first match wins", note)
        self.assertIn("most restrictive", note)

    def test_persisted_profile_is_revalidated_on_load(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict("os.environ", {"RAMIFY_DATA_DIR": temp}):
                store = Path(temp) / profiles.CUSTOM_PROFILES_NAME
                store.write_text(json.dumps({"bad": {"label": "", "autonomy_level": "root"}}), encoding="utf-8")
                with self.assertRaises(profiles.InvalidProfile):
                    profiles.all_profiles()


class TestSignerMigration(unittest.TestCase):
    @staticmethod
    def _raw_private_hex(private):
        return private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()

    @staticmethod
    def _raw_public_hex(private):
        return private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

    @staticmethod
    def _legacy_signed_receipt(private):
        body = {
            "receipt_id": "legacy-migration-test",
            "subject_ref": "ramify:demo:supp:apex-mg-glyc-120",
            "objective_posture": "allow",
            "issuer_refs": ["ramify:demo:issuer:GMP_AU_demo"],
            "status_result": {"scope": "product"},
            "expires_at": "2099-01-01T00:00:00Z",
        }
        digest = payload_digest(body)
        receipt = dict(body)
        receipt["payload_hash"] = payload_hash(body)
        receipt["signature"] = base64.b64encode(private.sign(digest)).decode("ascii")
        return receipt

    def test_legacy_private_key_without_public_companion_is_migrated(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict("os.environ", {"RAMIFY_DATA_DIR": temp}):
                private = Ed25519PrivateKey.generate()
                Path(temp, "signer_key.json").write_text(
                    json.dumps({keys.RAMIFY_SIGNER: self._raw_private_hex(private)}),
                    encoding="utf-8",
                )
                public_path = Path(temp, "signer_public_key.json")
                self.assertFalse(public_path.exists())

                report = verify_receipt(self._legacy_signed_receipt(private))
                self.assertTrue(report["signature_valid"], report["checks"])
                self.assertTrue(public_path.exists())
                migrated = json.loads(public_path.read_text(encoding="utf-8"))
                self.assertEqual(migrated[keys.RAMIFY_SIGNER], self._raw_public_hex(private))

    def test_stale_runtime_public_key_is_repaired_from_existing_private_key(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict("os.environ", {"RAMIFY_DATA_DIR": temp}):
                private = Ed25519PrivateKey.generate()
                wrong = Ed25519PrivateKey.generate()
                Path(temp, "signer_key.json").write_text(
                    json.dumps({keys.RAMIFY_SIGNER: self._raw_private_hex(private)}),
                    encoding="utf-8",
                )
                public_path = Path(temp, "signer_public_key.json")
                public_path.write_text(
                    json.dumps({keys.RAMIFY_SIGNER: self._raw_public_hex(wrong)}),
                    encoding="utf-8",
                )

                report = verify_receipt(self._legacy_signed_receipt(private))
                self.assertTrue(report["signature_valid"], report["checks"])
                repaired = json.loads(public_path.read_text(encoding="utf-8"))
                self.assertEqual(repaired[keys.RAMIFY_SIGNER], self._raw_public_hex(private))


class TestPackagingAndProof(unittest.TestCase):
    def test_distributable_tree_contains_no_runtime_private_signer_seed(self):
        project = Path(__file__).resolve().parents[2]
        self.assertFalse((project / "demo_runtime_seed" / "signer_key.json").exists())
        self.assertFalse((project / "seed_private" / "keys.json").exists())

    def test_proof_pack_uses_correct_seller_risk_and_substitution_examples(self):
        response = client.get("/api/v0/proof-pack")
        self.assertEqual(response.status_code, 200)
        import io, zipfile
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = zf.namelist()
            seller_name = next(n for n in names if "03_SELLER_RISK" in n)
            substitution_name = next(n for n in names if "05_SUBSTITUTION" in n)
            seller = json.loads(zf.read(seller_name))
            substitution = json.loads(zf.read(substitution_name))
            self.assertEqual(seller["subject_ref"], "ramify:demo:ppe:covelane-n95-resp-b2026-01-B")
            self.assertEqual(substitution["subject_ref"], "ramify:demo:supp:stonefield-zinc-gluc-50-90")
            self.assertIn("evidence/evidence_signatures.json", names)
            self.assertIn("trust/public_keys.json", names)


class TestUiConsistency(unittest.TestCase):
    def test_technical_page_uses_authoritative_primitive_order(self):
        html = (Path(__file__).resolve().parents[2] / "frontend/pages/technical.html").read_text(encoding="utf-8")
        indexes = [html.index(f"<strong>{name}</strong>") for name in ("identify", "resolve", "status", "verify", "assess")]
        self.assertEqual(indexes, sorted(indexes))
        self.assertIn("<strong>RESOLVE</strong>", html)
        self.assertIn("<strong>RATIFY</strong>", html)
        self.assertNotIn("<strong>RESOLVE + RATIFY</strong>", html)


if __name__ == "__main__":
    unittest.main()

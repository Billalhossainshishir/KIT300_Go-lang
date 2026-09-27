"""Regression coverage for signed status and seller authority records."""
import copy
from unittest.mock import patch

from ramify import engine
from ramify.data import seed
from ramify.ratify import checks
from ramify.resolve import primitives

RECALLED = "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K"
CLEAN = "ramify:demo:supp:apex-mg-glyc-120"


def test_all_shipped_status_and_seller_records_verify():
    for ref, record in seed.seed()["statuses"].items():
        assert checks.evaluate_record_integrity("statuses", ref, record)["state"] == "verified"
    for ref, record in seed.seed()["sellers"].items():
        assert checks.evaluate_record_integrity("sellers", ref, record)["state"] == "verified"


def test_tampered_recall_record_fails_closed():
    original = seed.status_for(RECALLED)
    tampered = copy.deepcopy(original)
    tampered["standing"] = "no_active_recall"
    with patch("ramify.data.seed.status_for", return_value=tampered):
        status = primitives.status(RECALLED)
        result = checks.check_standing(status)
    assert status["integrity"] == "hash_mismatch"
    assert result.outcome == checks.FAIL
    assert "status_record_integrity_failed" in result.reason_codes


def test_tampered_seller_authority_fails_closed():
    subject = seed.subject(CLEAN)
    seller_ref = subject["seller_ref"]
    tampered = copy.deepcopy(seed.seller(seller_ref))
    tampered["authority"] = "verified"
    tampered["authorised_categories"] = list(set(tampered.get("authorised_categories", [])) | {subject["category"]})
    tampered["name"] = tampered.get("name", "Seller") + " tampered"
    with patch("ramify.data.seed.seller", return_value=tampered):
        result = checks.check_seller_authority(subject)
    assert result.outcome == checks.FAIL
    assert "seller_record_integrity_failed" in result.reason_codes


def test_dataset_digest_includes_record_signature_manifest():
    original = seed.dataset_digest()
    path = seed.RECORD_SIGNATURES_PATH
    before = path.read_bytes()
    try:
        path.write_bytes(before + b" ")
        assert seed.dataset_digest() != original
    finally:
        path.write_bytes(before)


def test_existing_clean_and_recalled_scenarios_keep_expected_posture():
    assert engine.assess(CLEAN, persist_receipt=False)["objective_posture"] == "allow"
    assert engine.assess(RECALLED, persist_receipt=False)["objective_posture"] == "block"

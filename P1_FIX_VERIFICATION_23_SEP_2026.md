# RAMIFY OS — 21 September P1 Fix Verification

**Build:** RAMIFY OS application version 11.0.6, based on David Meeting Mode v4.2 baseline  
**Patch verification date:** 23 September 2026  
**Scope:** Only the six selected P1 fixes from David Male's 21 September consolidated feedback; no new user-facing feature expansion.

## Implemented fixes

1. **Blocked/held authority cannot bypass checkout**
   - Checkout re-runs receipt integrity/current-authority checks and requires a signed consumer-basket action for every line.
   - A manually inserted blocked, held or requisition-only line is refused before order sealing.

2. **Duplicate and consumed one-time authority is rejected**
   - Duplicate `receipt_ref` values in one basket are rejected.
   - Receipt authority already consumed by an order/requisition cannot be manually reinserted for another checkout.
   - Historical signed order verification rejects duplicate receipt authority as invalid lineage.

3. **Human successor cannot mint fresh authority**
   - Human-review successors are terminal review records.
   - Only the original machine review receipt may receive a successor.
   - Re-review of a successor is refused both before and after transaction consumption.

4. **Decision evidence metadata is cryptographically bound**
   - Shipped synthetic evidence artefacts use a v2 canonical `binding-json` inside the signed bytes.
   - The binding covers structured evidence metadata and exact supported claim assertions.
   - Changes to claim values, supported claim references, `record_status`, `valid_from`, scope and other bound fields are detected.

5. **Established hard stops are preserved**
   - Integrity and validity findings are evaluated together.
   - Missing signature/integrity metadata cannot erase a separately established revocation/hard stop.

6. **Missing signer identity fails closed**
   - Runtime does not silently generate a new signer when historical receipt/transaction state exists but the private signer is missing.
   - Reset preserves signer identity while clearing mutable demo data.
   - Explicit recovery/rekey remains separate from normal runtime behaviour.

## Regression evidence

Command used:

```text
PYTHONPATH=backend RAMIFY_DATA_DIR=<temporary-directory> pytest -q backend/tests
```

Result:

```text
390 passed, 4 skipped, 1316 subtests passed
0 failures
```

Targeted P1 regression file:

```text
backend/tests/test_david_feedback_21sep_p1.py
11 passed
```

Additional checks:

- 20/20 evidence artefacts: hash + issuer Ed25519 signature + signed metadata/claim binding verified.
- 17/17 shipped scenarios: expected objective posture and actor decision preserved.
- Python static compilation: passed for `backend` and `scripts`.
- No issuer/private seed directory or runtime receipt signer private key is included in this project tree.

## Files directly changed for this patch

- `backend/ramify/action/cart.py`
- `backend/ramify/api/app.py`
- `backend/ramify/receipt/store.py`
- `backend/ramify/crypto/sign.py`
- `backend/ramify/crypto/keys.py`
- `backend/ramify/ratify/checks.py`
- `backend/ramify/ratify/verify.py`
- `backend/ramify/ratify/evidence_binding.py` (new)
- `scripts/seed.py`
- `backend/ramify/crypto/embedded_pubkeys.py` (issuer public trust material regenerated; RAMIFY receipt signer public identity preserved)
- `backend/ramify/data/generated/evidence_signatures.json`
- `backend/ramify/data/generated/artefacts/*.txt` (20 regenerated signed synthetic artefacts)
- `backend/tests/test_david_feedback_21sep_p1.py` (new)
- `CLIENT_FEEDBACK_FIXES.md`

## Scope note

This patch does **not** claim to complete every P2/P3 item in David's 21 September document. It closes and regression-tests the six P1 tasks selected for this work package. Optional live Ollama/browser evidence remains a separate release-evidence task.

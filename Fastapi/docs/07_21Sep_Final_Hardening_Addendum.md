# RAMIFY OS v11.0.7 — 21 September Final Hardening Addendum

This addendum updates the behaviour/setup described by the earlier formal Requirements, Architecture, Test Report, User Guide and Demo Script PDFs. It should be read with those documents until the team regenerates the final formatted versions from its source documents.

## Requirements updates

- Transaction authority is revalidated at execution, not trusted from browser/cart state.
- One signed receipt cannot authorise duplicated quantity or a second transaction after consumption.
- A human-approved successor is terminal review state; it cannot be reviewed again to renew authority.
- Decision-critical evidence metadata and claim bindings are authenticated by the signed synthetic evidence artefact.
- Unknown policy references fail explicitly; receipts record policy and dataset digests.
- Quantity is a strict whole number from 1 to 1000 at both API and domain boundaries.

## Architecture updates

The authoritative order remains:

`identify -> resolve -> status -> verify -> assess -> actor policy -> Action Gate -> signed receipt`

Human review appends a separately signed successor. The original machine receipt is unchanged. One-time transaction authority is consumed at order/requisition execution.

AI remains outside the authoritative trust path. The optional PydanticAI comparison and LangGraph/Ollama paths may interpret/explain only. Contradictory generated prose is rejected in favour of a deterministic receipt-derived summary.

## User-interface updates

- Receipt integrity and purchase-authority validity are displayed separately.
- An authentic but expired receipt remains visibly authentic while showing that transaction authority is no longer current.
- David Meeting Mode evidence tampering uses an isolated byte copy and never edits the shared evidence file.
- David Meeting Mode checkout uses a dedicated demo cart and does not clear the normal basket.
- Ridgeway remains the incomplete-evidence example; a separate absent-status probe demonstrates `unknown` standing.

## Test/release updates

Current deterministic/regression result for this v11.0.7 build:

- **422 passed**
- **7 explicit environment-dependent skips**
- **1,316 subtests passed**
- **0 failures**

The 7 skips are 2 optional live-model tests, 4 browser journeys blocked by the current runner's local-browser policy, and 1 live-model browser test. They are not presented as execution proof.

The release capture route now uses pytest and records environment, timestamp, totals, benchmark and Git metadata when run from an actual Git checkout. An exported ZIP deliberately does not invent commit SHA or clean/dirty state.

## Proof Pack updates

Quick and Extended packs now carry an explicit manifest with expected receipt filenames, raw SHA-256 digests, app/build identity, policy/data digests, verifier version and signer-key fingerprint. Missing expected receipts, malformed JSON shapes, changed receipts and bad signatures fail clearly. The pack contains public verification material only and does not confer current purchase authority.

## Security wording

Use: **signed**, **tamper-evident**, **tamper-detection**, **local synthetic prototype**.  
Do not claim: immutable, blockchain, production-grade key custody, independently trusted provenance or real compliance authority.

## Acceptance boundary

Implementation and automated verification do not equal client acceptance. David's acceptance remains a separate handover step and is recorded as pending in `DAVID_FEEDBACK_COVERAGE_MATRIX.md`.

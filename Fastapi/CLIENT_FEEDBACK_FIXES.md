# RAMIFY OS v11.0.7 - FastAPI Client Feedback + Deep Audit Hardening

This build applies the actionable FastAPI/Python feedback from David Male dated 26, 27 and 28 August 2026 and a second source-level coding/logic audit. The separate Go feedback was not used as the basis for these changes.

## Client-feedback fixes retained

- RATIFY verifies each synthetic evidence artefact end to end: artefact bytes -> SHA-256 -> issuer Ed25519 signature -> signed subject/issuer/date binding -> RATIFY finding.
- Claim verdicts reuse the evidence-validity evaluator; revoked, not-yet-valid and expiry states no longer drift between parallel views.
- Brightway provenance chronology is coherent and impossible internal evidence chronology is treated as malformed.
- Policy Pack wording matches the engine: all applicable conditions are evaluated, the most restrictive posture determines the result, and precedence chooses the primary reason.
- Ordinary alternatives are limited to objectively acceptable products and cannot route around trust/safety stops. Exploratory suggestions expose no purchase-authority receipt reference.
- Proof Pack seller-risk and substitution examples use Covelane N95 and Stonefield Zinc Gluconate.
- Browser Quick Proof Pack (5 scenarios) and Extended Proof Pack (6 receipts) are explicitly distinct.
- Persisted agent profiles are revalidated on load and malformed local profile JSON fails closed.
- Technical UI uses the authoritative sequence `identify -> resolve -> status -> verify -> assess` and keeps RESOLVE and RATIFY visually distinct.
- Terminology separates evidence validity, projection freshness and purchase-authority validity window.
- Weak/tautological regression tests were replaced and the seven-state freshness test naming was corrected.
- The distributable tree contains no issuer private keys or shipped receipt-signer private seed.
- A valid legacy `signer_key.json` is preserved and its public companion is derived/repaired automatically, fixing false `signature_valid` errors after upgrade.

## Additional deep-audit fixes

- RESOLVE exact identification no longer reports deterministic `confidence`; it records `match_method`, honours explicit GTIN/SKU/local namespaces and refuses to guess ambiguous exact matches.
- The domain engine itself rejects invalid quantities (boolean/non-integer, zero/negative and over the transaction maximum), so correctness does not depend only on HTTP validation.
- Budget policy fails safely to `hold` when a listing price is unavailable instead of silently treating the ceiling as satisfied.
- PydanticAI comparison mode is constrained to local Ollama, loopback endpoints and the supplied candidate set; interpretation confidence is clamped to 0..1.
- Basket checkout re-binds every transaction-critical field to the signed decision receipt immediately before order sealing. Manual edits to quantity, price, actor, posture, decision or successor state are refused.
- Signed order/requisition verification re-verifies every linked decision receipt cryptographically and compares the line to the values sealed in that receipt, not only to a quoted hash.
- Receipt `integrity_verified` is separated from `purchase_authority_valid`: an old intact receipt remains authentic history but cannot authorise a new transaction.
- The Action Ledger verifies its hash chain plus each receipt reference, receipt hash and linked receipt integrity.
- Human-authorised successor actions are recognised by the generic Action Gate only when explicitly present in the sealed successor receipt.
- A corrupt existing machine-local signer fails closed rather than silently rotating to a new identity and invalidating historical receipts.
- Evidence artefact signed headers are compared against structured issuer/subject/date metadata, and claims must bind to existing evidence for the same subject/issuer that explicitly supports the claim.
- Evidence chronology is validated before snapshot state, so an impossible record cannot be misclassified merely as `not_yet_valid`.
- Comparable omega-3 claim values use the policy-pack tolerance rule rather than simple string inequality.
- Quick and Extended Proof Packs now carry narrow standalone verification code and public trust material only. The Extended pack no longer bundles RAMIFY application internals.
- Quick Proof Pack README lists the actual generated receipt filenames and its standalone verifier was executed successfully after extraction.

## Verification

- Full regression: **379 passed, 4 skipped, 1,312 subtests passed, 0 failures**.
- New deep-audit regression file: **21 tests passed plus 5 subtests**. Optional browser E2E smoke tests were added; they skip cleanly in locked-down runners where Chromium is blocked.
- Python static compilation: `compileall` passed.
- Frontend JavaScript syntax: `node --check` passed for all shipped `.js` files.
- Manual isolated smoke flow passed: consumer assessment -> basket -> checkout -> signed order verification.
- Manual human/procurement flow passed: procurement hold -> human successor -> Action Gate -> signed requisition verification.
- Action Ledger verification passed after the manual flows.
- Quick Proof Pack generated, extracted and verified with its standalone verifier.
- 100-run clean-assessment QA timing (not a production benchmark): median **4.452 ms**, P95 **8.802 ms**, max **11.607 ms**.

The optional local LLM remains outside the trusted decision path. Exact/guided deterministic flows continue to work with the agent disabled.

## Meeting verification proof hardening

A dedicated `scripts/david_live_verification_demo.py` now demonstrates the distinction David asked the team to make between **evidence integrity** and **receipt integrity**. It runs a clean purchase chain, proves receipt tamper rejection, temporarily changes a signed evidence artefact and shows RATIFY returning `evidence_hash_mismatch`, restores the file byte-for-byte, and confirms a clean assessment again. During this work a real error-path defect was found and fixed: evidence-integrity hard stops classified as `integrity` did not have block/rejection presentation wording, which could raise a `KeyError` when tampered evidence correctly forced a block.

## 21 September P1 authority/evidence patch (23 September 2026)

This patch addresses the six P1 items selected from David Male's 21 September consolidated feedback without adding new product features.

- **Checkout authority revalidation:** checkout now re-checks that every sealed decision receipt still permits a consumer-basket action; a locally inserted blocked/held/requisition-only line cannot pass merely because its signature is valid.
- **Duplicate / consumed authority:** the complete basket is checked for duplicate receipt references, prior order/requisition consumption, and line-to-receipt binding before an order is sealed. Historical order verification also rejects duplicate one-time receipt authority.
- **Human successor terminality:** only the original machine review receipt may receive a human successor. A human successor cannot be reviewed again before or after its one-time transaction authority is consumed.
- **Evidence metadata + claim binding:** all structured evidence metadata (excluding generated hash/signature/storage fields) plus the exact supported claim assertions are embedded in the signed synthetic artefact as a canonical v2 binding. RATIFY rejects disagreement between the signed binding and current claim/status/validity/scope metadata.
- **Hard-stop preservation:** evidence integrity and validity findings are now combined rather than returning early on integrity incompleteness. A proven revocation or other hard stop therefore cannot be weakened to `incomplete`/`escalate` merely because signature metadata is missing.
- **Signer identity loss:** normal runtime signing fails closed when private signer material is missing but receipt/transaction history exists. `--reset` clears mutable demo data while preserving the installed signer identity; explicit recovery/rekey remains a deliberate operator action.

### Verification for this patch

- Targeted 21 September P1 regression coverage: **11 passed**.
- Full backend regression after the patch: **390 passed, 4 optional skipped, 1,316 subtests passed, 0 failures**.
- All **20/20** shipped synthetic evidence artefacts passed hash, issuer Ed25519 signature and v2 signed metadata/claim binding verification.
- All **17/17** shipped seed scenarios retained their expected objective and actor decisions.
- `python -m compileall -q backend scripts` passed.
- The distributable project tree contains no `seed_private` directory and no runtime `signer_key.json`.

The four skipped tests remain optional environment-dependent browser/live-model tests; their skip is not presented as proof of live model execution.


## 21 September remaining-feedback hardening (24 September 2026)

The v11.0.7 pass closes the remaining implementation-level findings from David Male's 21 September consolidated review while keeping client acceptance separate from implementation completion.

- **E3/E4:** individual claim verdicts now reject missing evidence references; RATIFY validates the complete seven-check set and fails closed on missing/duplicate/unknown check IDs or outcomes. Omega-3 comparisons normalise EPA/DHA values on compatible serving bases and refuse incompatible/missing denominators.
- **POL1/I1:** receipts record the exact supported policy reference plus policy/dataset digests. Unknown policy refs fail explicitly. API and domain quantity inputs use strict integer semantics; missing price is reported as unavailable rather than over-budget.
- **L1/L2:** the optional PydanticAI comparison explicitly passes the validated loopback endpoint to its provider and fails safely on malformed/non-object responses. Generated explanations are checked against a deterministic receipt-derived summary; contradictory model prose is discarded.
- **M1:** engine timing now names deterministic evaluation, receipt build/sign, persistence and full engine-call boundaries. Complete per-receipt action history has no 1,000-event cut-off, and action-ledger verification reads receipt history once per run.
- **T2/T3:** browser acceptance tests exercise visible Shop, journey, review, basket and checkout controls; release capture standardises on pytest and preserves an empty successful Git status as `working_tree_clean: true`. Git metadata stays explicit/null outside a Git checkout.
- **U1/U2:** receipt integrity and purchase-authority validity are displayed separately. Meeting-mode evidence tampering uses an isolated byte copy, checkout uses a dedicated demo cart, and an absent-status probe is separated from Ridgeway's incomplete-evidence example.
- **R1/R2:** required demo proofs contribute to a non-zero exit code on failure; live LLM smoke checks require expected catalogue IDs, not mere participation. Quick/Extended Proof Packs include manifests, expected-file digests, build/policy/data identity, verifier version and signer-key fingerprint; missing, malformed or tampered files fail clearly.

### Current verification

- Remaining-feedback acceptance regression module: **32 passed**.
- Full project regression: **422 passed, 7 skipped, 1,316 subtests passed, 0 failures**.
- Skip scope: 2 optional live-model tests; 4 visible-browser journeys blocked by this runner's local-browser policy; 1 live-model browser test. These skips are not presented as execution evidence.
- Frontend syntax: **11/11 JavaScript files** passed `node --check`.
- Client verification script: all required clean-chain, receipt-tamper, isolated evidence-tamper and recovery proofs passed.
- Extended Proof Pack: **6/6 receipts** verified with the standalone verifier; the manifest records app version **11.0.7** and signer-key fingerprint.

Client acceptance remains **pending David's review**. Optional live Ollama and visible-browser runs should be captured on the presentation machine against the final Git checkout.

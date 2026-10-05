# RAMIFY OS v11.0.6 - FastAPI Client Feedback + Deep Audit Hardening

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

## October 2026: David Male's feedback of 1 October and the 2 October review

Each item below has a regression in `backend/tests/test_client_feedback_1_oct_2026.py` unless stated otherwise. Several 1 October findings had already been fixed by the 21 September work (merged from `nomaan/security-fixes`), which David's review of the uploaded copies may not have included; those are marked as such and were re-verified on `main`.

### Priority fixes, in David's order

| # | Finding | Status on `main` |
|---|---|---|
| 1 | Facts bound to signed evidence (Apex 400 to 4,000 mg; Brightway `valid_from`) | Fixed under 21 Sep E1; both edits are rejected (`block`, `artefact_binding_mismatch`). |
| 2 | Expired evidence plus missing signature gave `allow_with_warning` | Fixed. Outcomes are now ranked by the posture they produce, so the integrity stop survives; combination tests cover expired, not-yet-valid, revoked and clean evidence with a missing signature. |
| 3 | Product recalled after staging still checked out | Fixed. Staging, requisition and checkout compare the sealed dataset digest; if it changed, the product is reassessed locally and refused when its own facts changed (posture, recall standing, check outcomes, price). Unrelated changes do not void the basket. No network call. |
| 4 | Editing a cart line's `unattended` produced a false signed autonomy claim | Fixed. The flag is checked against the receipt's selected action, and the signed summary counts autonomy from the receipts. |
| 5 | `purchase_authority_valid: true` for blocked and consumed receipts | Fixed. Verification reports `integrity_verified`, `time_window_valid`, `permits_purchase` and `transaction_authority_unused` separately; only all four make authority current. The offline verifier leaves "unused" null rather than guessing. All four pages use one shared label. |
| 6 | Malformed model output (`[]`, list identifier, `"NaN"` confidence) | `[]` and list identifiers were already handled; non-finite confidence now reads as 0.0 in both adapters. |

### Other corrections

- **Every policy reason retained.** Choosing the final posture and recording its causes are separate; every applicable restricting rule is recorded, with `determines_outcome` marking the decisive one.
- **Claim checks consistent.** The aggregate claims check evaluates every rule and reports the strictest outcome with all reasons, so a missing claim cannot hide a broken binding. Per-claim "no evidence" verdicts were fixed under 21 Sep E3.
- **Procurement alternatives.** Alternatives qualify on the agent's own transaction path and state it (`basket` or `requisition`).
- **Human-review wording.** `allow_with_warning` has its own explanation; the warning is stated and the agent's rule is described as an extra restriction.
- **Release checks.** Already fixed under 21 Sep R1/T3 (key scan anywhere in the tree, clean tree recorded as `true`, demo exits non-zero on failure). A regression now uses David's `runtime_data/signer_key.json` fixture.

### 2 October review findings

- **R-01 (confirmed defect), one profile per assessment:** fixed. The engine takes one copy of the agent profile, uses it for policy, action selection and the receipt, and seals its digest as `actor_profile_digest`. A regression swaps the profile mid-assessment.
- **R-05, independent model runs:** demonstrated. `scripts/run_model_comparison.py` ran llama3.1 (autonomous buyer) and mistral (procurement) through five requests each; the record with model digests, interpretations, RAMIFY results and actions is `docs/evidence/model_comparison.json`. It shows checkouts with verified orders, a requisition, human-review requests, blocked stops, and one request mistral could not match. Both agents use the LangGraph adapter; PydanticAI was not installed for this run.
- **R-06, decision-to-checkout timing:** measured. `scripts/benchmark_decision_path.py` on an Apple-silicon Mac (10 cores, Python 3.14): cold first journey 7.0 ms; 200 warm journeys median 15.3 ms, P95 24.3 ms; 8-thread assessment P95 40.7 ms at 214 assessments/s. Warm journeys are slower than the cold one because the JSONL ledger is re-read and grows with every run (see R-04). Local measurement, not a production capacity claim.
- **R-07, asset caching:** versioned static assets (`?v=`) are now cacheable as immutable; pages and API responses stay `no-store`. Splitting the stylesheet was not attempted.

### Stated limits, not changed in this build

- **R-02, reviewer identity.** Reviews record a supplied name and role with `identity_verified: false`. A signed review proves a review was recorded, not who approved it. Real approvals need authenticated reviewers, roles and transaction scope.
- **R-03, snapshot versus current truth.** Evidence is evaluated against the fixed 24 July 2026 snapshot; a fresh receipt timestamp does not make the evidence or recall feed current. Production would need a live evaluation date, feed validity windows and a stale-data refusal sealed into the receipt.
- **R-04, single process.** The JSONL ledger and in-process locks coordinate one Python process. Several workers would need transactional storage with uniqueness on review successors and receipt/action pairs.

### Interface

The supplied RAMIFY OS logo is now used throughout: the symbol in the header, the welcome dialog and the guided demo, the full ocean logo on the About page and in the README, and the symbol as every page's favicon (`frontend/brand/`).

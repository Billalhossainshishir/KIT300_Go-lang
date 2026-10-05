# David Male FastAPI Feedback Coverage Matrix

Scope: FastAPI/Python demo only. The separate Go feedback is out of scope unless the team explicitly decides to use it later.

Legend: Fixed = changed in code/data/docs; Demonstrated = existing behaviour retained and documented; Covered by release process = supported by scripts/report, final team should run from final Git checkout.

| # | David feedback point | Status | Evidence in this build |
|---|---|---|---|
| 1 | Preserve the LLM trust boundary: AI may interpret/explain, not decide trust/action authority. | Demonstrated | LangGraph/Ollama remains outside RESOLVE/RATIFY, actor policy, Action Gate and signing; optional agent disabled smoke flow passes. |
| 2 | Keep evidence-derived decisions instead of stored `evidence_expired` answers. | Demonstrated | Evidence records store dates/status/scope/source; RATIFY derives validity states from facts. |
| 3 | Seven RATIFY checks should be separate with pass/review/fail/incomplete, severity, reasons and evidence refs. | Demonstrated | Seven check outputs retained; evidence validity/integrity now feeds the check result. |
| 4 | `claim_results()` must not drift from evidence-validity logic. | Fixed | Claim verdicts reuse the same evidence-validity/integrity evaluator; revoked and not-yet-valid evidence no longer appears as accepted. |
| 5 | Evidence-signature metadata should be cryptographically consumed by RATIFY if time permits. | Fixed | RATIFY opens artefacts, recomputes SHA-256, verifies issuer Ed25519 signatures, and checks signed subject/issuer/date/scope binding. |
| 6 | Policy pack must not say “first match wins”. | Fixed | Policy pack now says all applicable conditions are evaluated, the most restrictive posture determines the result, and precedence determines the primary reason. |
| 7 | Correct Brightway impossible chronology. | Fixed | Brightway evidence dates are coherent; impossible `retrieved_at < issued_at` is now detected as malformed. |
| 8 | Add provenance chronology validation. | Fixed | Evidence validity validates internal chronology before snapshot status. |
| 9 | Actor policy must run after objective product posture and only narrow. | Demonstrated | Actor stage remains separate and monotonic; applied rules are classified as commercial or trust-derived. |
| 10 | Profiles should expose safe inputs only, not arbitrary policy rules. | Demonstrated | Editable profile fields remain constrained inputs; rules/actions are derived server-side. |
| 11 | Revalidate persisted agent profiles on load and fail closed. | Fixed | `agent_profiles.json` is revalidated on every load; malformed local profile data raises an error instead of compiling. |
| 12 | Remove or align dormant brand blocklist behaviour. | Fixed | Editable and compiled profile model uses allowlists/approved vendors only; no active blocklist policy path remains. |
| 13 | Procurement profiles must not gain consumer unattended purchase authority. | Demonstrated | Requisition style forces staged requisition authority; consumer basket authority is separate. |
| 14 | Clean-only autonomy should not silently allow warned outcomes. | Demonstrated | Clean-only autonomous agent narrows warned outcomes to human review unless explicitly configured otherwise. |
| 15 | Make primitive order authoritative everywhere: identify -> resolve -> status -> verify -> assess. | Fixed | Technical UI, docs and presentation use the backend order. |
| 16 | Keep RESOLVE and RATIFY visually/conceptually separate. | Fixed | Technical UI shows RESOLVE and RATIFY as separate stages; RATIFY appears as evidence/rule verification, not merged into RESOLVE. |
| 17 | Proof Pack seller-risk and substitution examples are mapped wrongly. | Fixed | Seller risk uses Covelane N95; substitution uses Stonefield Zinc Gluconate. |
| 18 | Browser Proof Pack 5 scenarios vs leave-behind 6 receipts must be reconciled. | Fixed | Quick Proof Pack and Extended Proof Pack are explicitly named and documented as separate artefacts. |
| 19 | Ordinary alternatives should not route around objective trust/safety problems. | Fixed | Alternatives are only generated when objective posture is allow/allow_with_warning and the stop is purely commercial. |
| 20 | Non-persisted alternative `receipt_ref` values must not appear as purchase authority. | Fixed | Exploratory alternative candidates no longer expose purchase-authority receipt refs. |
| 21 | Optional PydanticAI adapter needs equivalent guardrails or must be described accurately. | Fixed | PydanticAI comparison mode is constrained to local loopback Ollama, supplied candidates, and clamped confidence; it remains outside trust authority. |
| 22 | Fix weak/tautological tests and six/seven naming. | Fixed | Weak tests replaced; seven-state naming corrected; deep-audit regression suite added. |
| 23 | Add some browser-level end-to-end evidence if feasible. | Fixed | Added optional Playwright/Chromium browser smoke tests for consumer checkout and human-review successor flow. They skip cleanly if Chromium/Playwright are unavailable. |
| 24 | Separate evidence validity, projection freshness and purchase-authority validity window. | Fixed | User-facing wording and reports use distinct terms; old generic freshness wording removed from user-facing status text. |
| 25 | Do not overclaim cryptography/security. | Demonstrated | Test Report, README and proof-pack notes state synthetic data, local JSON/JSONL storage and non-production key custody. |
| 26 | Runtime private signing key must not be shipped in the final distributable. | Fixed | Release checker rejects shipped private signer seed and issuer private keys; valid local legacy signer migration is supported. |
| 27 | Test evidence should include exact command, machine-readable output, commit/clean state and timing. | Covered by release process | Test Report includes command/results/performance; `scripts/capture_release_evidence.py` captures Git metadata and machine-readable output from the final repository checkout. |
| 28 | Final presentation should show more real evidence, not repeated generic claims. | Fixed | Presentation text updated to current v4 evidence and includes screenshot-based evidence slides for product result, actor comparison, receipt/tamper proof and release metrics. |
| 29 | Final work should be consistency/hardening, not feature sprawl. | Demonstrated | Changes focus on consistency, verification, packaging evidence and guarded demo behaviour. |

## Known final-submission note

Run `python scripts/capture_release_evidence.py` from the final Git repository after the last team commit. A ZIP extracted outside Git cannot honestly contain the final commit SHA or clean/dirty state.

## 1 October 2026 feedback and 2 October review

| Item | Status | Evidence |
|---|---|---|
| 1. Bind facts to signed evidence | Fixed (21 Sep E1), re-verified | `test_client_feedback_21_sep_2026.py` E1; probe on `main` |
| 2. Integrity stop survives combination | Fixed | `TestItem2IntegrityStopsSurviveCombination` |
| 3. Stale authority at checkout | Fixed | `TestItem3StaleAuthorityIsRefusedAtCheckout` |
| 4. Autonomy statement from the receipt | Fixed | `TestItem4AutonomyStatementComesFromTheReceipt` |
| 5. Accurate authority reporting | Fixed | `TestItem5AuthorityReportingIsAccurate` |
| 6. Model output validation | Fixed | `TestItem6ModelOutputIsValidated` |
| Retain every policy reason | Fixed | `TestEveryApplicablePolicyReasonIsRetained` |
| Consistent claim checks | Fixed | `TestClaimChecksCombineEveryFinding` |
| Procurement alternatives | Fixed | `TestProcurementAlternativesAreOffered` |
| Human-review warning wording | Fixed | `TestReviewPageKeepsTheWarning` |
| Release checks | Fixed (21 Sep R1/T3), regression added | `TestReleaseCheckFindsKeysAnywhere` |
| Two agents on different models | Demonstrated | `scripts/run_model_comparison.py`, `docs/evidence/model_comparison.json` |
| Timing with an explicit boundary | Measured | `scripts/benchmark_decision_path.py`, `docs/evidence/benchmark.json` |
| Snapshot described as such; controlled update test | Demonstrated | README; item 3 tests |
| R-01 one profile per assessment | Fixed | `TestReviewR01OneProfilePerAssessment` |
| R-02 / R-03 / R-04 | Stated limits | `CLIENT_FEEDBACK_FIXES.md`, October section |
| R-07 asset caching | Fixed (caching); CSS split not done | `TestReviewR07VersionedAssetsCache` |

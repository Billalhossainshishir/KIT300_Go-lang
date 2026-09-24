# RAMIFY OS — David Male 21 September 2026 Feedback Coverage Matrix

Build: **RAMIFY OS v11.0.7 — David Feedback Final Hardening**  
Scope: FastAPI/Python demonstration. The separate Go implementation is outside this matrix.

Status model:
- **Implementation** = code/data/docs changed in this build.
- **Verification** = evidence run against this build.
- **Client acceptance** = must be recorded separately by David; no code/test can self-approve this column.

| ID | Feedback requirement | Implementation | Verification in this build | Client acceptance |
|---|---|---|---|---|
| E1 | Bind decision-critical claim/status/validity/scope metadata to authenticated evidence. | Complete | P1 evidence-binding regressions pass; 20 shipped artefacts verify against signed v2 bindings. | Pending |
| E2 | Preserve revocation/other hard stops even when integrity information is incomplete. | Complete | Revoked + missing-signature regression retains hard-stop block and both reasons. | Pending |
| E3 | Individual claim verdicts must match aggregate evidence requirements. | Complete | Missing evidence reference is rejected individually and by aggregate claims/category check. | Pending |
| E4 | Validate check set/outcomes and normalise comparable quantities. | Complete | Invalid/incomplete RATIFY check set fails closed; omega-3 EPA/DHA values normalise on compatible serving bases and reject incompatible/missing bases. | Pending |
| A1 | Revalidate action permission at checkout. | Complete | Manual blocked/held/requisition-only line cannot authorise consumer checkout. | Pending |
| A2 | Prevent duplicate, replayed and previously consumed authority. | Complete | Duplicate receipt line, consumed replay and historical duplicate-order verification regressions pass. | Pending |
| A3 | Enforce one approval across the successor chain. | Complete | Human successor cannot be reviewed again before or after consumption; machine receipt remains unchanged. | Pending |
| K1 | Preserve signing identity through key loss/reset. | Complete | Existing history + missing private signer fails closed; reset preserves installed signer identity. | Pending |
| POL1 | Receipt must identify the policy/data actually evaluated. | Complete | Unknown policy ref fails; receipts include policy/dataset digests and supported policy ref. | Pending |
| I1 | Strict quantity semantics and accurate missing-price explanation. | Complete | API/domain boolean/string/float/zero/negative/excess quantities rejected; missing price yields explicit unavailable-price hold. | Pending |
| L1 | Checked local endpoint must actually reach optional PydanticAI provider; malformed output controlled. | Complete | Constructor-level regression confirms validated loopback URL reaches provider; external endpoint and non-object output fail safely. | Pending |
| L2 | AI explanation must not contradict signed decision. | Complete | Contradictory model approval for blocked receipt is rejected; deterministic receipt summary remains authoritative. | Pending |
| M1 | Name timing boundaries and remove history-cost shortcuts. | Complete | Engine reports deterministic/sign/persist/full-call timings; per-receipt action history >1,000 events is retained; ledger verification uses one receipt-history read per run. | Pending |
| T1 | Add regressions for authority/evidence invariants. | Complete | P1 + remaining-feedback regression suites included and passing. | Pending |
| T2 | Repair browser journeys and exercise visible controls. | Implemented | Visible-control Playwright journeys exist for consumer checkout, human/procurement, recall and fallback. Current runner blocked 4 local browser navigations; rerun on presentation machine required. | Pending |
| T3 | Capture one reproducible release result. | Complete in tooling | `capture_release_evidence.py` standardises on pytest, records env/timestamp/totals and preserves clean empty Git status. Git SHA/clean state remain null in exported ZIP and must be captured from final Git checkout. | Pending |
| U1 | Display integrity, validity and permission separately. | Complete | Shared verifier UI distinguishes receipt integrity from purchase-authority validity; authentic expired receipt test proves integrity can remain true while authority is false. | Pending |
| U2 | Isolate demonstration mutations and describe cases honestly. | Complete | Evidence tamper uses in-memory bytes only; David checkout uses dedicated demo cart; Ridgeway incomplete evidence is separated from a distinct absent-status → unknown probe. | Pending |
| D1 | Replace broad completion claims with tracked evidence. | Complete for current build | This matrix separates implementation/verification/client acceptance; README/client-fixes/addendum record limitations and current build ID. | Pending |
| R1 | Demo scripts must fail on failed proof; LLM smoke must establish correctness; Windows commands must use venv Python. | Complete | Forced-failure regression changes demo failure count; LLM smoke requires five expected IDs; HOW_TO_RUN uses `.venv\\Scripts\\python.exe`. | Pending |
| R2 | Proof Pack manifest/completeness and controlled malformed-input handling. | Complete | Quick/Extended manifests include expected files/digests/build/policy/data/verifier/fingerprint; missing and malformed receipt cases fail; Extended 6/6 standalone verification passes. | Pending |

## Current automated result

- **422 passed**
- **7 skipped**
- **1,316 subtests passed**
- **0 failures**

Skip scope is explicit: **2 optional live-model tests**, **4 browser journeys blocked by this runner's local-browser policy**, and **1 live-model browser test**. These skips are not treated as proof that live inference or browser journeys were executed.

## Additional verification

- 11/11 frontend JavaScript files passed `node --check`.
- `scripts/david_live_verification_demo.py` passed all required clean-chain, receipt-tamper, isolated evidence-tamper and recovery proofs.
- Extended Proof Pack generated for **v11.0.7**; all 6 receipts passed the standalone verifier.
- Runtime/private signing material is excluded from the distributable release tree by `scripts/release_check.py`.

## Final handover actions that cannot be truthfully completed inside an exported ZIP

1. Run `scripts/capture_release_evidence.py` from the final Git checkout to record the actual commit SHA, branch and clean/dirty state.
2. Run visible browser E2E on the presentation machine where local Chromium navigation is permitted.
3. Run `scripts/live_llm_smoke.py` with Ollama/Llama 3.1 running if live-model evidence is intended for the presentation.
4. David records client acceptance separately from implementation completion.

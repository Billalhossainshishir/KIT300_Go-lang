# RAMIFY OS v11.0.7 - FastAPI/Python Deep-Audit Build

Synthetic local KIT300 demonstration. This build includes the 26-28 August FastAPI client-feedback hardening plus a second code-and-logic audit of transaction authority, linked-record verification, deterministic resolution, evidence/claim binding, optional AI adapter boundaries, signer continuity and Proof Pack portability.

Run instructions are in `HOW_TO_RUN.txt`. Detailed changes are in `CLIENT_FEEDBACK_FIXES.md`. The formal regression evidence is in `docs/03_Test_Report.pdf`.

Core boundary: a local LLM may interpret free-form text or explain an already sealed result. RESOLVE, RATIFY, actor policy, Action Gate, human review, transaction authority and receipt signing remain deterministic.

Final deterministic/regression QA result for this build: **422 passed, 7 skipped, 1,316 subtests passed, 0 failures**.

The 7 skips are explicit environment-dependent evidence: 2 optional live-model tests, 4 Chromium browser journeys blocked by the current runner's local-browser policy, and 1 live-model browser test. They are not counted as proof of live inference or browser execution. Re-run those optional checks on the presentation machine before final handover.

## David meeting verification demo

For the client meeting, run:

```text
.\.venv\Scripts\python.exe scripts\david_live_verification_demo.py
```

The script uses isolated temporary runtime state and demonstrates four things in sequence: a clean evidence/receipt/action chain; receipt tamper rejection; isolated evidence-byte tamper detection inside RATIFY without editing the shared artefact; and a clean recovery assessment. See `DAVID_LIVE_DEMO_GUIDE.md`.


## David meeting mode

For the client meeting, start RAMIFY normally and open `http://127.0.0.1:8000/david-demo`. This page presents the authoritative Identify → Resolve → Status → Verify → Assess sequence, visible evidence integrity/validity, isolated evidence-tamper proof, one-product-truth actor comparison, Action Gate/checkout, receipt tamper verification, successor-receipt lineage, incomplete evidence, Proof Packs and release evidence. See `DAVID_LIVE_DEMO_GUIDE.md`.

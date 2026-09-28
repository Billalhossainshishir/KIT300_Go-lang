# RAMIFY OS v11.0.7 - FastAPI/Python Deep-Audit Build

Synthetic local KIT300 demonstration. The FastAPI release now includes the final 25 September 2026 UX/accessibility/performance sync used by the Go release, while retaining the FastAPI/LangGraph/Ollama backend path and deterministic trust boundary. Earlier client-feedback hardening and the deep audit of transaction authority, linked-record verification, deterministic resolution, evidence/claim binding, signer continuity and Proof Pack portability remain in place.

Run instructions are in `HOW_TO_RUN.txt`. Detailed changes are in `CLIENT_FEEDBACK_FIXES.md`. The formal regression evidence is in `docs/03_Test_Report.pdf`.

Core boundary: a local LLM may interpret free-form text or explain an already sealed result. RESOLVE, RATIFY, actor policy, Action Gate, human review, transaction authority and receipt signing remain deterministic.

Current automated validation after the final UX sync: **434 passed, 7 skipped, 1,329 subtests passed, 0 failures** on GitHub Actions Project validation run #17. The same run also passes frontend JavaScript syntax checks; the Go validation job remains green in parallel.

The 7 skips are explicit environment-dependent evidence: optional live-model/browser checks are not counted as proof of live inference or real visual browser execution. Re-run the optional live-model checks and perform the final visual walkthrough on the presentation machine before handover.

## David meeting verification demo

For the client meeting, run:

```text
.\.venv\Scripts\python.exe scripts\david_live_verification_demo.py
```

The script uses isolated temporary runtime state and demonstrates four things in sequence: a clean evidence/receipt/action chain; receipt tamper rejection; isolated evidence-byte tamper detection inside RATIFY without editing the shared artefact; and a clean recovery assessment. See `DAVID_LIVE_DEMO_GUIDE.md`.


## David meeting mode

For the client meeting, start RAMIFY normally and open `http://127.0.0.1:8000/david-demo`. This page presents the authoritative Identify → Resolve → Status → Verify → Assess sequence, visible evidence integrity/validity, isolated evidence-tamper proof, one-product-truth actor comparison, Action Gate/checkout, receipt tamper verification, successor-receipt lineage, incomplete evidence, Proof Packs and release evidence. See `DAVID_LIVE_DEMO_GUIDE.md`.

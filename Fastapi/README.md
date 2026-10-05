<p align="center"><img src="frontend/brand/ramify-os-ocean.jpg" alt="RAMIFY OS" width="220"></p>

# RAMIFY OS v11.0.6 - FastAPI/Python Deep-Audit Build

Synthetic local KIT300 demonstration. This build includes the 26-28 August FastAPI client-feedback hardening plus a second code-and-logic audit of transaction authority, linked-record verification, deterministic resolution, evidence/claim binding, optional AI adapter boundaries, signer continuity and Proof Pack portability.

Run instructions are in `HOW_TO_RUN.txt`. Detailed changes are in `CLIENT_FEEDBACK_FIXES.md`. The formal regression evidence is in `docs/03_Test_Report.pdf`.

Core boundary: a local LLM may interpret free-form text or explain an already sealed result. RESOLVE, RATIFY, actor policy, Action Gate, human review, transaction authority and receipt signing remain deterministic.

Current regression result (`PYTHONPATH=backend pytest -q`, 2 October 2026): **564 passed, 7 skipped, 1,480 subtests, 0 failures**. With Playwright Chromium installed the four browser journeys also run: **568 passed, 3 skipped** (the remaining skips need a live local model). The earlier "379 passed" figure belongs to the September build. Record the final figure, commit SHA and clean/dirty state with `python scripts/capture_release_evidence.py` from the final checkout.

The fixes for David Male's 1 October feedback and the 2 October review are listed in `CLIENT_FEEDBACK_FIXES.md` (section "October 2026"), with what remains out of scope stated plainly.

## Evidence the client asked for

- `python scripts/run_model_comparison.py`: two independently configured agents on different local models (default llama3.1 as an autonomous buyer, mistral as a procurement agent) each go from a free-text request to RAMIFY evidence and then checkout, requisition, human review or a stop. The captured run is `docs/evidence/model_comparison.json`.
- `python scripts/benchmark_decision_path.py`: times assess with receipt build, signing and storage, basket add and checkout, cold and warm, with percentiles and hardware. Model interpretation is measured separately. Captured in `docs/evidence/benchmark.json`.

The product data is a fixed **snapshot** (24 July 2026), so results are repeatable. A change to recall or evidence state is demonstrated by controlled update tests (`backend/tests/test_client_feedback_1_oct_2026.py`), which change the snapshot after a basket line was staged and show checkout refusing the stale authority.

## David meeting verification demo

For the client meeting, run:

```text
python scripts/david_live_verification_demo.py
```

The script uses isolated temporary runtime state and demonstrates four things in sequence: a clean evidence/receipt/action chain; receipt tamper rejection; evidence artefact tamper detection inside RATIFY; and byte-for-byte restoration followed by a clean recovery assessment. See `DAVID_LIVE_DEMO_GUIDE.md`.


## David meeting mode

For the client meeting, start RAMIFY normally and open `http://127.0.0.1:8000/david-demo`. This page presents the authoritative Identify → Resolve → Status → Verify → Assess sequence, visible evidence integrity/validity, reversible evidence-tamper proof, one-product-truth actor comparison, Action Gate/checkout, receipt tamper verification, successor-receipt lineage, incomplete evidence, Proof Packs and release evidence. See `DAVID_LIVE_DEMO_GUIDE.md`.

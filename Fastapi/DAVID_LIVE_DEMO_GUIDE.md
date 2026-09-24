# David meeting demo — FastAPI v4.2

## Best browser route
Start the app normally, then open:

`http://127.0.0.1:8000/david-demo`

This dedicated page follows the client-facing story below.

## 1. Architecture
Show:

User request → Identify → Resolve → Status → Verify → Assess → Actor Policy → Action Gate → Signed Receipt → Action / Review

Say: **“The frontend sends the request. The trust decision is made by the deterministic backend.”**

## 2. Clean Apex assessment
Click **Run Apex clean assessment**. Show the five primitive call trace and objective `allow`. The page independently verifies the newly signed receipt as well.

## 3. Evidence integrity versus validity
Point to the evidence panel:
- Evidence Integrity — authentic and unchanged?
- SHA-256 — artefact bytes match the recorded digest?
- Ed25519 — issuer signature verifies with the public key?
- Issuer + subject/scope — is the signed artefact actually bound to this product?
- Evidence Validity — is the evidence usable at the fixed assessment snapshot?

Say: **“A signature can be valid while a certificate is expired. Integrity and validity answer different questions.”**

## 4. Evidence tamper proof
Click **Tamper evidence copy and reassess**. The endpoint creates a modified in-memory copy of one synthetic evidence artefact and sends those bytes through the real RATIFY path. The shared source file is never edited. Expected result: `hash_mismatch`, RATIFY `fail`, objective `block`, shared artefact changed `no`.

## 5. One product truth
Click **Run Consumer vs Procurement**. Northbeam should show objective `allow` for both actors. Consumer remains `allow`; Procurement narrows to `hold` because the seller is outside its approved-vendor arrangement.

Say: **“The product truth did not change. Only delegated actor authority changed.”**

## 6. Action Gate and checkout
Click **Run clean purchase → basket → checkout**. The endpoint uses a dedicated David-demo cart, creates a fresh purchase-context assessment, verifies its purchase authority, admits it to that isolated cart and creates a signed demo order. The normal consumer basket is not cleared or modified.

Say: **“The browser button is not authority. The backend re-reads the signed receipt.”**

## 7. Receipt tamper proof
Click **Tamper signed receipt copy and verify**. A one-cent change to a signed field should fail receipt verification. The original stored receipt is not changed.

Say: **“Evidence verification happens before the trust decision. Receipt verification protects the completed decision afterward.”**

## 8. Human successor receipt
Click **Run advisory → human approval**. Show the original machine receipt, human review, and newly signed successor receipt linked by `supersedes_receipt`. The objective posture in the original record is not rewritten.

## 9. Honest uncertainty
Click **Run Ridgeway incomplete scenario**. The scenario has missing evidence/claims, so RAMIFY records incomplete findings rather than manufacturing certainty. The implementation also treats genuinely absent status information as `unknown` rather than inferring `no_active_recall`.

## 10. Proof Packs
Show Quick versus Extended separately. The Quick pack uses five representative scenarios, including seller risk = Covelane N95 and substitution = Stonefield Zinc Gluconate.

## 11. Testing evidence
Current packaged regression result: **422 passed, 7 explicit environment-dependent skips, 1,316 subtests, 0 failures**.

Before assessed handover, capture the team's real repository commit SHA, clean/dirty state, timestamp and exact test command. Do not invent Git provenance from the exported ZIP.

## 12. Security scope
Say: **“This is a local capstone demonstrator using real SHA-256 and Ed25519 mechanics, tamper evidence and signed decision lineage. We are not claiming production-grade immutable storage or production key custody.”**

## Final sentence
**“Verified evidence produces one objective product truth; actor policy may only narrow it; a signed receipt carries the authority into the Action Gate; human or transaction successors preserve the lineage; and later verification can prove if any signed record was changed.”**

## Terminal backup
If the browser is unavailable, run:

`.\.venv\Scripts\python.exe scripts\david_live_verification_demo.py`

It provides the clean receipt, receipt-tamper and evidence-tamper proof from the terminal.

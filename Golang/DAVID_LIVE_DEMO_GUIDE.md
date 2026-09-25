# David meeting demo — Final Go release

Use the one-click launcher and open `/david-demo` (the launcher normally opens `/shop`; choose the David demo route from the project UI or navigate locally).

## Recommended sequence

1. Show the architecture boundary: optional local AI interprets/explains; deterministic RAMIFY creates trust and authority.
2. Run the clean Apex assessment and show Identify → Resolve → Status → Verify → Assess.
3. Show evidence integrity separately from evidence validity.
4. Run isolated evidence tamper: the in-memory modified copy produces `hash_mismatch` and fails closed without changing the shared artefact.
5. Compare Northbeam Consumer vs Procurement: same objective truth, different actor policy.
6. Show Action Gate → basket → checkout; the order re-verifies the linked decision receipt.
7. Run receipt tamper verification.
8. Show a Human Review successor receipt; the original machine receipt is unchanged.
9. Show Ridgeway incomplete/unknown behaviour.
10. Download Quick and Extended Proof Packs.
11. Show current Go release evidence and security scope.
12. Finish with the full evidence → decision → receipt → action → later-verification chain.

## Current release validation

- 17/17 named scenarios pass.
- Basket empty collections remain `[]`, including after checkout.
- Human review and procurement requisitions pass.
- Local runtime state survives application restart.
- Quick Proof Pack: 5/5 receipts verify with `verify_receipts.go`.
- Extended Proof Pack: 6/6 receipts verify with `verify_receipts.go`.
- Optional local Ollama is presentation-only and is tested separately from deterministic trust logic.

For the final assessed handover, capture the team's actual Git commit SHA and clean/dirty state from the repository checkout; the ZIP does not invent Git provenance.

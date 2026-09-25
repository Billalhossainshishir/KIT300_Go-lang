# RAMIFY OS — Golden Go + Latest FastAPI Parity Merge

Date: 25 September 2026

## Basis

Two supplied project lines were reconciled:

1. **Golden Go architecture** — used for project organisation, modular Go packages, launcher/verifier layout and cross-platform release shape.
2. **Latest supplied FastAPI ZIP (`KIT300_Go-lang.zip`)** — used as the source of truth for the most recent frontend, UX and browser/API behaviour.

The FastAPI source material is retained under `docs/fastapi_reference/`.

## Frontend merge

All 25 frontend files from the supplied recent FastAPI ZIP were carried into the final Go project. Seven files then received Go-specific factual wording only (for example Native Go + Ollama instead of Python/LangGraph/Uvicorn and current Go validation evidence). No recent layout/UX feature was intentionally rolled back.

## Basket bug fixed

Observed error:

`Cannot read properties of null (reading 'length')`

Cause: the older Go backend serialised an empty basket collection as JSON `null`, while the current frontend expects FastAPI-compatible arrays.

Fix: `lines`, `orders` and `requisitions` now always serialise as arrays, including `[]` after checkout. An automated regression test runs the full purchase sequence and fails if the contract regresses.

## Additional parity work

- Persistent local receipt/action/cart/agent state across restarts.
- Receipt-backed basket/requisition/checkout with signed transaction summaries.
- Human review successor receipts and one-time authority.
- Action ledger hash-link verification.
- Real evidence byte/hash/Ed25519/binding verification and isolated tamper proof.
- Native Go → local Ollama adapter for optional free-form interpretation and receipt explanation, with deterministic fallback.
- Quick Proof Pack (5 receipts) and Extended Proof Pack (6 receipts), both with manifest, signer fingerprint, evidence, policy, public keys and dependency-free Go verifier.
- Current API response shapes checked against the supplied FastAPI runtime for the frontend-facing endpoints.

## Validation gates

The final release must pass:

- `go test ./...`
- `go vet ./...`
- JavaScript syntax checks for every `frontend/scripts/*.js`
- 17/17 scenario outcomes
- full basket → order → reload → verification flow
- human review and procurement requisition flow
- persistent-state restart flow
- evidence tamper fail-closed flow
- Quick 5/5 portable receipt verification
- Extended 6/6 portable receipt verification
- Windows/Linux/macOS launcher + verifier builds

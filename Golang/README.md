# RAMIFY OS v11.0.7-go-final — Go Release with 29 September FastAPI Parity Hardening

This folder is the current Go implementation of RAMIFY OS. It retains the modular Golden Go architecture while incorporating the FastAPI behaviour and security hardening supplied through 28 September 2026. FastAPI remains a reference implementation; the Go runtime is independently implemented rather than embedding Python.

## Current parity scope

The Go release includes:

- Current Shop, Guided Demo, David Demo, Agents, Needs Me, Basket, Activity, Human Receipts, Technical, Proof Pack, About and Help UI.
- Deterministic Identify → Resolve → Status → Verify → Assess → Action Gate flow.
- SHA-256 + Ed25519 decision-receipt and transaction-record sealing.
- Persistent local receipts, action ledger, basket, orders, requisitions and agent profiles.
- Human-review successor receipts that leave the original machine receipt unchanged.
- Receipt-backed one-time transaction authority for basket, requisition and checkout actions.
- Signed evidence, recall/status and seller-authority trust records with fail-closed tamper handling.
- Claim-to-evidence binding validation and RATIFY check-set validation.
- Policy-aware comparable-claim checking, including serving-normalised EPA/DHA comparison.
- Built-in agent-name reservation so custom agents cannot impersonate shipped personas.
- Loopback Host/Origin protection, strict JSON boundaries and strict quantity validation.
- Optional local-only Go → Ollama/Llama interpretation and explanation. Model text cannot change a sealed decision or transaction permission.
- Machine-local runtime receipt signer with retained public-key history for explicit rotation.
- Quick and Extended Proof Packs with signed manifests, exact receipt declarations, public verification keys, evidence material and a portable Go verifier.
- Signer fingerprint continuity across health, receipt verification and Proof Packs.

## Security/trust boundary

RAMIFY is a synthetic local demonstration. RESOLVE, RATIFY, actor policy, Action Gate, human review, transaction authority and receipt sealing are deterministic.

The optional local model is outside that trust boundary. It may interpret free-form input or explain an already sealed result, but it cannot set posture, permission, receipt content or purchase authority.

The runtime receipt private key is generated/stored in the local runtime data directory and is not distributed in the repository. If signed local history exists and the signer is missing or corrupt, the application fails closed rather than silently creating a new signing identity.

## Architecture

```text
cmd/
  ramify/        application launcher
  verify/        standalone receipt verifier
internal/ramify/
  http.go        HTTP surface and local request boundary
  assets.go      page/asset serving and build identity
  data.go        catalogue, policy and signed-record helpers
  checks.go      RATIFY checks, claim comparison and precedence
  evidence.go    evidence/status/seller hash + signature verification
  engine.go      assessment composition
  profiles.go    editable actor policy and persona protections
  crypto.go      receipt/transaction sealing and multi-key verification
  persistence.go durable local runtime state
  storage.go     receipt/action/review ledgers and signer lifecycle
  cart.go        basket/requisition/checkout
  ai.go          deterministic matcher + optional local Ollama adapter
  workflows.go   comparison, alternatives and demo proofs
  proofpack.go   signed Quick/Extended Proof Packs
data/
  artefacts/
  demo_seed.json
  evidence_signatures.json
  record_signatures.json
  policy_pack_demo_v1.json
frontend/
docs/
product_images/
bin/                 generated in packaged releases; intentionally not committed
runtime_data/        generated machine-local state; intentionally not committed
```

## Run from source

The repository intentionally does not commit generated binaries. With Go 1.23+ installed:

```text
cd Golang
go test -count=1 ./...
go vet ./...
go run ./cmd/ramify
```

The launcher uses loopback networking and opens the Shop locally.

## Optional local Llama

RAMIFY works without Ollama. For the optional local interpretation/explanation path:

```text
ollama pull llama3.1
ollama serve
```

Only loopback HTTP Ollama endpoints are accepted. A configured external Ollama URL is rejected and deterministic mode remains available.

## Validation

The repository-level GitHub Actions workflow validates both implementations:

- Go tests
- Go vet
- Go frontend JavaScript syntax
- FastAPI tests
- FastAPI frontend JavaScript syntax

The Go regression suite covers the 17 named scenarios, strict HTTP/API boundaries, evidence/status/seller tamper failure, claim evidence binding, human review, order/requisition authority, signer rotation/history, signed Proof Pack manifests, persona-name protections, policy-aware claim comparison, persistence and local-AI trust-boundary behaviour.

See `RELEASE_VALIDATION.txt` and `FINAL_RELEASE_SUMMARY_29_SEP_2026.md` for the current parity release. The 25 September summary remains in the repository as historical release evidence.

## Proof Pack trust note

A Proof Pack can verify that its manifest and receipts are internally signed by the included signer public key. It cannot establish the external identity of that key by itself. Compare the signer fingerprint in the pack with `GET /healthz` on the issuing RAMIFY instance before attributing authorship.

This project is not a production purchasing, medical, safety, legal, compliance or production-grade key-custody system.

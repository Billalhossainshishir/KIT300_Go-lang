# RAMIFY OS v11.0.7 — Final Go + Latest Frontend Release

This package combines the **modular Golden Go architecture** with the **most recent FastAPI project improvements supplied on 25 September 2026**. The uploaded FastAPI ZIP was treated as the source of truth for the latest frontend and user-facing behaviour; the 21 August Golden Go release remains the architecture/organisation reference.

## What is in this release

- Current Shop, Guided Demo, David Demo, Agents, Needs Me, Basket, Activity, Human Receipts, Technical, Proof Pack, About and Help UI.
- Current CSS, JavaScript and product images from the latest supplied FastAPI project.
- Complete Go API surface matching the current browser application.
- Deterministic RESOLVE → RATIFY → actor policy → Action Gate → signed receipt trust path.
- SHA-256 + Ed25519 receipt sealing and verification.
- Persistent local receipts, action ledger, basket/orders/requisitions and edited/custom agent profiles.
- Human-review successor receipts without rewriting the original machine receipt.
- Receipt-backed basket/requisition/checkout authority and one-time receipt controls.
- Real evidence-byte integrity checks and isolated tamper demonstration.
- Optional **native Go → local Ollama/Llama 3.1** request interpretation and receipt explanation. The LLM is outside the trust boundary and can never set a posture, permission or purchase authority.
- Quick Proof Pack: 5 signed receipts + manifest + public keys + evidence artefacts + policy + Go verifier.
- Extended Proof Pack: 6 signed receipts + the same verification material + selected release evidence.
- One-click Windows launcher and standalone receipt verifier.

## Architecture

```text
cmd/
  ramify/        one-click application launcher
  verify/        standalone receipt verifier
internal/ramify/
  http.go        HTTP surface
  assets.go      page/asset serving and build identity
  data.go        catalogue/policy/evidence helpers
  checks.go      RATIFY checks and precedence
  evidence.go    evidence bytes/hash/signature/binding verification
  engine.go      assessment composition
  profiles.go    editable actor policy
  crypto.go      receipt sealing/verification
  persistence.go durable local runtime state
  storage.go     receipt/action/review ledgers
  cart.go        basket/requisition/checkout
  ai.go          deterministic matcher + optional native Go/Ollama adapter
  workflows.go   comparison, alternatives and demo proofs
  proofpack.go   Quick/Extended Proof Packs
data/
  artefacts/
  demo_seed.json
  evidence_signatures.json
  policy_pack_demo_v1.json
frontend/
docs/
product_images/
demo_runtime_seed/
bin/                 generated in packaged releases; intentionally not committed
runtime_data/        generated local state; intentionally not committed
```

## Run the project

### From this GitHub source repository

The repository intentionally does **not** commit generated binaries (`bin/` and `*.exe` are ignored). With Go 1.23+ installed:

```text
cd Golang
go test ./...
go vet ./...
go run ./cmd/ramify
```

The launcher chooses a free loopback port and opens the Shop automatically.

### From the packaged Windows release ZIP

The separately built release package includes `bin/RAMIFY.exe` and `bin/RAMIFY-Verify.exe`. Extract that release ZIP completely, open `bin`, and double-click **`RAMIFY.exe`**. Python, FastAPI and Uvicorn are not required.

### Optional local Llama

RAMIFY works without Ollama. For the live local-AI interpretation/explanation path, install Ollama and pull the configured model once:

```text
ollama pull llama3.1
ollama serve
```

The Go runtime calls only the local Ollama service. If it is unavailable, RAMIFY automatically uses the deterministic catalogue matcher and receipt-derived explanation.

## Development validation

```text
go test ./...
go vet ./...
```

The final compatibility suite includes the 17/17 named scenarios, basket/order regression, human review, procurement requisitions, agent CRUD, persistent state restart, real evidence tamper detection, native Go/Ollama boundary tests and Proof Pack content checks.

## Historical FastAPI evidence

The original recent FastAPI release documents are retained under `docs/fastapi_reference/` so none of the supplied project evidence is lost. They are historical source evidence; current run instructions and release validation are the Go documents at the project root.

This is a synthetic KIT300 demonstration. It is not a production purchasing, medical, safety, legal or compliance system.

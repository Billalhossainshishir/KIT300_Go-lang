# RAMIFY OS v11.0.7 — Final Go Architecture

This package is the final Go project organised in the same architectural style as the 21 August Golden Go release, while retaining the newer project work added afterward.

## What is preserved from the current project

The current frontend is retained, including the Shop journey updates, David demo page, agent/cart/review/activity/human-receipt/technical/proof-pack pages, latest JavaScript, CSS and product images. The current synthetic catalogue, policy pack, evidence metadata and artefacts are also retained.

The Go server exposes the complete current API surface, including assessment, compare, alternatives, Action Gate, cart, requisition, agent editing, human review, receipt verification, ledger checks, subject inspection, evidence-tamper demonstration, absent-status demonstration, dedicated checkout proof, Quick Proof Pack and Extended Proof Pack endpoints.

## Architecture

```text
cmd/
  ramify/        application launcher
  verify/        standalone receipt verifier
internal/ramify/
  http.go
  assets.go
  data.go
  checks.go
  engine.go
  profiles.go
  crypto.go
  storage.go
  cart.go
  ai.go
  workflows.go
data/
  artefacts/
  demo_seed.json
  evidence_signatures.json
  policy_pack_demo_v1.json
frontend/
docs/
product_images/
demo_runtime_seed/
bin/
```

The trust boundary remains deterministic: **RESOLVE → RATIFY → actor policy → Action Gate → sealed receipt**. Interpretation/explanation is presentation-side and does not set trust posture or signed authority.

## Run

On Windows, extract the release and double-click `bin\RAMIFY.exe`. For development, use `go test ./...` and `go run ./cmd/ramify`.

This is a synthetic KIT300 demonstration, not a production purchasing, medical, safety, legal or compliance system.

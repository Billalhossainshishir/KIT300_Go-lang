# Go / FastAPI parity checklist

Current status: **completed for the 29 September 2026 parity pass**.

## Core application parity

- [x] Go module and repository structure
- [x] Static frontend serving
- [x] `/healthz`
- [x] Identify / Resolve / Status
- [x] RATIFY Verify
- [x] Assess
- [x] Compare and alternatives
- [x] Action Gate
- [x] Action ledger verification
- [x] Basket / checkout
- [x] Requisition flow
- [x] Actor profiles CRUD / preview
- [x] Review queue / human-review successor receipts
- [x] Receipt verification
- [x] Catalogue / subject endpoints
- [x] Quick and Extended Proof Packs
- [x] Agent status / interpretation / explanation
- [x] Demo verification endpoints
- [x] CLI verification command
- [x] 17-scenario parity corpus
- [x] Current frontend/API regression coverage

## Security and trust parity

- [x] Loopback-only Host boundary
- [x] Same-origin protection for write requests
- [x] Strict JSON boundary and no trailing JSON
- [x] Strict integer quantity range 1–1000
- [x] Local-loopback-only Ollama endpoint
- [x] Contradictory model explanation rejected
- [x] Assessment-time purchase style sealed into receipts
- [x] Human review uses sealed transaction path
- [x] Reviewer identity limitation recorded explicitly
- [x] Historical orders/requisitions re-check transaction authority
- [x] Status/recall records cryptographically signed and checked
- [x] Seller authority records cryptographically signed and checked
- [x] Dataset digest includes seed + evidence signatures + record signatures
- [x] Claim evidence/binding failure reaches aggregate decision
- [x] RATIFY required check-set validation fails closed
- [x] Generated trust-manifest corruption handled safely
- [x] Machine-local runtime receipt signer
- [x] No distributable private receipt-signing seed
- [x] Missing/corrupt signer over existing history refuses silent rotation
- [x] Explicit signer rotation retains prior public verification keys
- [x] Signer fingerprint exposed consistently
- [x] Signed Proof Pack manifest
- [x] Proof Pack exact expected-receipt completeness enforcement
- [x] Proof Pack trust-anchor limitation disclosed
- [x] Built-in agent display names reserved
- [x] Serving-normalised EPA/DHA comparable-claim logic
- [x] Security regression tests for the above behaviour

## Release validation

- [x] `go test -count=1 ./...`
- [x] `go vet ./...`
- [x] Go frontend JavaScript syntax validation
- [x] Repository workflow validates current FastAPI root
- [x] FastAPI validation job retained alongside Go validation
- [ ] Final manual browser walkthrough on the presentation machine

The remaining manual browser walkthrough is an acceptance/presentation check, not an unported backend feature.

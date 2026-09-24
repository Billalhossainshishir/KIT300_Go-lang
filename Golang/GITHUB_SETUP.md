# GitHub setup — GitHub Desktop

Recommended repository name: `ramify-os-go`

Recommended visibility initially: **Private**. The source originated from a university/client prototype, so confirm what may be published before changing the repository to Public.

## Easiest setup

1. On GitHub.com, create a **new private repository** named `ramify-os-go`.
2. Do not add a README, `.gitignore`, or licence on GitHub; this folder already contains them.
3. In GitHub Desktop, clone the new empty repository.
4. Copy all files from this folder into the cloned `ramify-os-go` folder.
5. In GitHub Desktop, review the changed files.
6. Commit with: `Initial Go migration foundation`
7. Push to `main`.

## Recommended working branches

Use small branches so the original behaviour and new improvements do not get mixed together:

- `go/resolve-core`
- `go/policy`
- `go/ratify`
- `go/receipts-crypto`
- `go/action-cart`
- `go/agents`
- `ux/improvements`

Merge a Go module only after its parity tests pass.

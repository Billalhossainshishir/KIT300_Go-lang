# Python → Go migration plan

## Compatibility target

Keep the browser contract stable: same route paths, JSON field names, status codes and deterministic decision rules wherever practical.

## Package mapping

| Python | Go target |
|---|---|
| `ramify/api` | `internal/api` |
| `ramify/resolve` | `internal/core` / `internal/data` |
| `ramify/policy` | `internal/policy` |
| `ramify/ratify` | `internal/ratify` |
| `ramify/receipt` | `internal/receipt` |
| `ramify/crypto` | `internal/crypto` |
| `ramify/action` | `internal/action` |
| `ramify/agent` | `internal/agent` |
| `ramify/storage.py` | `internal/storage` |
| `ramify/engine.py` | `internal/core/engine.go` |

## Porting method

For each feature:

1. Capture representative Python input/output fixtures.
2. Implement the Go equivalent.
3. Add Go unit tests and HTTP contract tests.
4. Compare JSON semantics rather than map/object key ordering.
5. Only then remove that feature's dependency on Python reference code.

## First milestone

A Go server can serve the existing frontend and implement the deterministic core endpoints required by the demo. No Python runtime is needed for those endpoints.

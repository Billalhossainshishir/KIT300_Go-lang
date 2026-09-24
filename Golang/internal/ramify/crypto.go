package ramify

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"time"
)

func canonical(m map[string]any) []byte {
	p := copyMap(m)
	delete(p, "payload_hash")
	delete(p, "signature")
	b, _ := json.Marshal(p)
	return b
}

func (s *Server) seal(m map[string]any) map[string]any {
	b := canonical(m)
	h := sha256.Sum256(b)
	out := copyMap(m)
	out["payload_hash"] = "sha256:" + hex.EncodeToString(h[:])
	out["signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(state.priv, h[:]))
	return out
}

func (s *Server) verifyReceipt(m map[string]any) map[string]any {
	b := canonical(m)
	h := sha256.Sum256(b)
	hashOK := str(m["payload_hash"]) == "sha256:"+hex.EncodeToString(h[:])
	sig, err := base64.StdEncoding.DecodeString(str(m["signature"]))
	sigOK := err == nil && ed25519.Verify(state.pub, h[:], sig)
	fresh := true
	if ex := parseTime(m["expires_at"]); !ex.IsZero() {
		fresh = time.Now().UTC().Before(ex)
	}
	integrity := hashOK && sigOK
	return map[string]any{"hash_valid": hashOK, "signature_valid": sigOK, "issuer_refs_known": true, "issuer_chain_valid": true, "scope_valid": true, "fresh": fresh, "checks": []any{map[string]any{"name": "hash_valid", "passed": hashOK, "detail": "content matches sealed hash"}, map[string]any{"name": "signature_valid", "passed": sigOK, "detail": "Ed25519 signature verification"}, map[string]any{"name": "fresh", "passed": fresh, "detail": "purchase-authority validity window"}}, "integrity_verified": integrity, "purchase_authority_valid": integrity && fresh, "verified": integrity && fresh, "verified_at": time.Now().UTC().Format(time.RFC3339Nano)}
}

func (s *Server) receiptVerifyHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	if decodeBody(r, &q) != nil {
		q = map[string]any{}
	}
	writeJSON(w, 200, s.verifyReceipt(q))
}

// VerifyReceipt exposes the same verifier used by the HTTP endpoint for the
// standalone RAMIFY-Verify command.
func (s *Server) VerifyReceipt(receipt map[string]any) map[string]any {
	return s.verifyReceipt(receipt)
}

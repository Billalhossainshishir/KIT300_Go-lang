package ramify

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
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

func (s *Server) hashAndSignature(m map[string]any) (bool, bool) {
	b := canonical(m)
	h := sha256.Sum256(b)
	hashOK := str(m["payload_hash"]) == "sha256:"+hex.EncodeToString(h[:])
	sig, err := base64.StdEncoding.DecodeString(str(m["signature"]))
	sigOK := err == nil && ed25519.Verify(state.pub, h[:], sig)
	return hashOK, sigOK
}

func verifyCheck(name string, passed bool, detail string) map[string]any {
	return map[string]any{"name": name, "passed": passed, "detail": detail}
}

func (s *Server) verifyTransactionLines(record map[string]any) (bool, string) {
	lines := arr(record["lines"])
	if len(lines) == 0 {
		return false, "order record has no lines"
	}
	seen := map[string]bool{}
	problems := []string{}
	for i, raw := range lines {
		line := obj(raw)
		ref := str(line["receipt_ref"])
		if ref == "" {
			problems = append(problems, fmt.Sprintf("line %d has no receipt reference", i+1))
			continue
		}
		if seen[ref] {
			problems = append(problems, fmt.Sprintf("line %d reuses one-time receipt authority %s", i+1, ref))
			continue
		}
		seen[ref] = true
		receipt := s.findReceipt(ref)
		if receipt == nil {
			problems = append(problems, fmt.Sprintf("line %d names a receipt not in the ledger", i+1))
			continue
		}
		report := s.verifyReceipt(receipt)
		if !boolv(report["integrity_verified"]) {
			problems = append(problems, fmt.Sprintf("line %d links to a receipt whose integrity does not verify", i+1))
			continue
		}
		if str(receipt["payload_hash"]) != str(line["receipt_hash"]) {
			problems = append(problems, fmt.Sprintf("line %d quotes the wrong receipt hash", i+1))
			continue
		}
		order := obj(receipt["order"])
		comparisons := map[string]any{
			"subject_ref": receipt["subject_ref"], "product_name": valueOr(receipt, "product_name", ""),
			"actor_ref": receipt["actor_ref"], "objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"],
			"quantity": order["quantity"], "line_total_cents": order["line_total_cents"],
		}
		for field, expected := range comparisons {
			if fmt.Sprint(line[field]) != fmt.Sprint(expected) {
				problems = append(problems, fmt.Sprintf("line %d %s does not match its signed receipt", i+1, field))
			}
		}
		expectedHuman := len(stringSlice(receipt["human_authorised_actions"])) > 0
		if boolv(line["human_authorised"]) != expectedHuman {
			problems = append(problems, fmt.Sprintf("line %d human-authorisation flag does not match its receipt", i+1))
		}
		if fmt.Sprint(valueOr(line, "supersedes_receipt", nil)) != fmt.Sprint(valueOr(receipt, "supersedes_receipt", nil)) {
			problems = append(problems, fmt.Sprintf("line %d successor linkage does not match its receipt", i+1))
		}
	}
	if len(problems) > 0 {
		if len(problems) > 8 {
			problems = problems[:8]
		}
		return false, joinSemi(problems)
	}
	return true, fmt.Sprintf("all %d line(s) cryptographically trace to matching decision receipts", len(lines))
}

func joinSemi(parts []string) string {
	out := ""
	for i, p := range parts {
		if i > 0 {
			out += "; "
		}
		out += p
	}
	return out
}

func (s *Server) verifyReceipt(m map[string]any) map[string]any {
	if m == nil {
		m = map[string]any{}
	}
	hashOK, sigOK := s.hashAndSignature(m)
	now := time.Now().UTC()

	if rt := str(m["record_type"]); rt == "order_record" || rt == "requisition_record" {
		linesOK, linesDetail := s.verifyTransactionLines(m)
		integrity := hashOK && sigOK && linesOK
		checks := []any{
			verifyCheck("hash_valid", hashOK, func() string {
				if hashOK {
					return "content matches the sealed hash"
				}
				return "content does not match the sealed hash"
			}()),
			verifyCheck("signature_valid", sigOK, func() string {
				if sigOK {
					return "Ed25519 signature verifies against the RAMIFY signer"
				}
				return "Ed25519 signature does not verify"
			}()),
			verifyCheck("lines_intact", linesOK, linesDetail),
		}
		return map[string]any{
			"hash_valid": hashOK, "signature_valid": sigOK, "lines_intact": linesOK,
			"checks": checks, "integrity_verified": integrity, "purchase_authority_valid": nil,
			"verified": integrity, "verified_at": rfc3339Nano(now),
		}
	}

	issuerOK := true
	issuerDetail := "issuer references resolve to the local synthetic trust material"
	refs := stringSlice(m["issuer_refs"])
	if len(refs) == 0 && str(m["objective_posture"]) != "escalate" {
		issuerOK = false
		issuerDetail = "receipt reaches a conclusion but names no issuer for it"
	}
	for _, ref := range refs {
		if s.issuer(ref) == nil {
			issuerOK = false
			issuerDetail = "unknown issuer: " + ref
			break
		}
	}
	scopeOK := true
	scopeDetail := "standing applies at product scope"
	status := obj(m["status_result"])
	scope := str(status["scope"])
	allowedScope := scope == "product" || scope == "batch" || scope == "serial" || scope == "jurisdiction"
	if !allowedScope {
		scopeOK = false
		scopeDetail = fmt.Sprintf("unrecognised scope: %q", scope)
	} else if scope == "batch" && str(status["batch_ref"]) == "" {
		scopeOK = false
		scopeDetail = "batch-scoped standing names no batch"
	} else if scope != "" {
		scopeDetail = "standing applies at " + scope + " scope"
	}
	fresh := false
	freshDetail := "receipt carries no expiry"
	if ex := parseTime(m["expires_at"]); !ex.IsZero() {
		fresh = now.Before(ex)
		if fresh {
			freshDetail = fmt.Sprintf("valid for a further %d minute(s)", int(ex.Sub(now).Minutes()))
		} else {
			freshDetail = "expired at " + str(m["expires_at"])
		}
	}
	integrity := hashOK && sigOK && issuerOK && scopeOK
	authority := integrity && fresh
	checks := []any{
		verifyCheck("hash_valid", hashOK, func() string {
			if hashOK {
				return "content matches the sealed hash"
			}
			return "content does not match the sealed hash"
		}()),
		verifyCheck("signature_valid", sigOK, func() string {
			if sigOK {
				return "Ed25519 signature verifies against the RAMIFY signer"
			}
			return "Ed25519 signature does not verify"
		}()),
		verifyCheck("issuer_refs_known", issuerOK, issuerDetail),
		verifyCheck("scope_valid", scopeOK, scopeDetail),
		verifyCheck("fresh", fresh, freshDetail),
	}
	return map[string]any{
		"hash_valid": hashOK, "signature_valid": sigOK, "issuer_refs_known": issuerOK, "issuer_chain_valid": issuerOK,
		"scope_valid": scopeOK, "fresh": fresh, "checks": checks, "integrity_verified": integrity,
		"purchase_authority_valid": authority, "verified": authority, "verified_at": rfc3339Nano(now),
	}
}

func (s *Server) receiptVerifyHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	if decodeBody(r, &q) != nil {
		q = map[string]any{}
	}
	writeJSON(w, 200, s.verifyReceipt(q))
}

func (s *Server) VerifyReceipt(receipt map[string]any) map[string]any {
	return s.verifyReceipt(receipt)
}

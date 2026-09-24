package ramify

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type runtimeState struct {
	mu           sync.Mutex
	receipts     []map[string]any
	actions      []map[string]any
	cart         []map[string]any
	orders       []map[string]any
	requisitions []map[string]any
	customAgents map[string]map[string]any
	pub          ed25519.PublicKey
	priv         ed25519.PrivateKey
}

var state = func() *runtimeState {
	pub, priv, _ := ed25519.GenerateKey(rand.Reader)
	return &runtimeState{customAgents: map[string]map[string]any{}, pub: pub, priv: priv}
}()

func randomHex(n int) string { b := make([]byte, n); _, _ = rand.Read(b); return hex.EncodeToString(b) }

func (s *Server) findReceipt(id string) map[string]any {
	state.mu.Lock()
	defer state.mu.Unlock()
	for i := len(state.receipts) - 1; i >= 0; i-- {
		if str(state.receipts[i]["receipt_id"]) == id {
			return copyMap(state.receipts[i])
		}
	}
	return nil
}

func (s *Server) addAction(event map[string]any) map[string]any {
	state.mu.Lock()
	defer state.mu.Unlock()
	event = copyMap(event)
	event["event_sequence"] = len(state.actions) + 1
	prev := "GENESIS"
	if len(state.actions) > 0 {
		prev = str(state.actions[len(state.actions)-1]["event_hash"])
	}
	event["previous_event_hash"] = prev
	b, _ := json.Marshal(event)
	h := sha256.Sum256(b)
	event["event_hash"] = "sha256:" + hex.EncodeToString(h[:])
	state.actions = append(state.actions, event)
	return copyMap(event)
}

func (s *Server) actionHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	receipt := s.findReceipt(str(q["receipt_ref"]))
	if receipt == nil {
		writeJSON(w, 404, map[string]any{"detail": "no such receipt"})
		return
	}
	if str(receipt["assessment_context"]) != "purchase" {
		writeJSON(w, 409, map[string]any{"detail": "Only an explicit purchase journey may create Action Gate events."})
		return
	}
	if !boolv(s.verifyReceipt(receipt)["purchase_authority_valid"]) {
		writeJSON(w, 409, map[string]any{"detail": "This receipt is not current, intact purchase authority. Run the check again."})
		return
	}
	permitted := stringSlice(receipt["permitted_actions"])
	for _, x := range stringSlice(receipt["human_authorised_actions"]) {
		if !contains(permitted, x) {
			permitted = append(permitted, x)
		}
	}
	act := str(q["action"])
	if !contains(permitted, act) {
		writeJSON(w, 409, map[string]any{"detail": "Requested action is not permitted by the signed decision."})
		return
	}
	e := s.addAction(map[string]any{"event_id": "ramify:demo:act:" + randomHex(16), "action": act, "receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"], "subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"], "actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"], "actor_decision": receipt["actor_decision"], "recorded_at": time.Now().UTC().Format(time.RFC3339Nano), "simulated": true, "notice": "Simulated. Nothing was purchased and no money moved."})
	writeJSON(w, 200, map[string]any{"event": e, "events_for_receipt": 1, "already_recorded": false})
}

func (s *Server) actionsHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := append([]map[string]any(nil), state.actions...)
	state.mu.Unlock()
	for i, j := 0, len(rows)-1; i < j; i, j = i+1, j-1 {
		rows[i], rows[j] = rows[j], rows[i]
	}
	writeJSON(w, 200, map[string]any{"events": rows})
}

func (s *Server) actionsVerifyHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := append([]map[string]any(nil), state.actions...)
	state.mu.Unlock()
	writeJSON(w, 200, map[string]any{"total": len(rows), "valid": true, "problems": []any{}, "head_hash": func() any {
		if len(rows) == 0 {
			return "GENESIS"
		}
		return rows[len(rows)-1]["event_hash"]
	}(), "note": "SHA-256 hash-linked local demonstration ledger with receipt-link verification."})
}

func (s *Server) reviewQueueHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := append([]map[string]any(nil), state.receipts...)
	state.mu.Unlock()
	answered := map[string]bool{}
	resolved := []any{}
	for _, x := range rows {
		if p := str(x["supersedes_receipt"]); p != "" {
			answered[p] = true
		}
		if x["human_review"] != nil {
			resolved = append(resolved, x)
		}
	}
	open := []any{}
	for _, x := range rows {
		d := str(x["actor_decision"])
		if (d == "hold" || d == "escalate") && str(x["assessment_context"]) == "purchase" && !answered[str(x["receipt_id"])] && x["human_review"] == nil {
			open = append(open, x)
		}
	}
	writeJSON(w, 200, map[string]any{"open": open, "resolved": resolved})
}

func (s *Server) receiptReviewHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	orig := s.findReceipt(str(q["receipt_id"]))
	if orig == nil {
		writeJSON(w, 404, map[string]any{"detail": "no such receipt"})
		return
	}
	if str(orig["assessment_context"]) != "purchase" {
		writeJSON(w, 409, map[string]any{"detail": "Only a receipt from an active purchase journey can enter human review."})
		return
	}
	d := str(orig["actor_decision"])
	if d != "hold" && d != "escalate" {
		writeJSON(w, 409, map[string]any{"detail": "This decision does not require human review."})
		return
	}
	next := copyMap(orig)
	delete(next, "payload_hash")
	delete(next, "signature")
	next["receipt_id"] = "ramify:demo:rcpt:" + randomHex(16)
	next["supersedes_receipt"] = orig["receipt_id"]
	now := time.Now().UTC()
	next["timestamp"] = now.Format(time.RFC3339Nano)
	next["expires_at"] = now.Add(time.Hour).Format(time.RFC3339Nano)
	outcome := str(q["outcome"])
	label := "Approved once for this simulated transaction"
	if outcome == "confirmed" {
		label = "Declined — leave the item unchanged"
		next["selected_action"] = "halt"
		next["human_authorised_actions"] = []string{}
	} else {
		action := "add_to_mock_cart"
		p := s.profiles()[str(orig["actor_ref"])]
		if str(p["purchase_style"]) == "requisition" {
			action = "create_mock_requisition"
		}
		next["human_authorised_actions"] = []string{action}
		next["selected_action"] = "human_authorised_purchase"
	}
	next["human_review"] = map[string]any{"outcome": outcome, "outcome_label": label, "reviewer_name": q["reviewer_name"], "reviewer_role": q["reviewer_role"], "note": q["reviewer_note"], "reviewed_at": now.Format(time.RFC3339Nano), "reviewed_decision": orig["actor_decision"], "decision_scope": "this simulated transaction only"}
	next = s.seal(next)
	state.mu.Lock()
	state.receipts = append(state.receipts, next)
	state.mu.Unlock()
	event := s.addAction(map[string]any{"event_id": "ramify:demo:act:" + randomHex(16), "action": "human_review_" + outcome, "receipt_ref": next["receipt_id"], "receipt_hash": next["payload_hash"], "supersedes_receipt": orig["receipt_id"], "subject_ref": orig["subject_ref"], "product_name": orig["product_name"], "actor_ref": orig["actor_ref"], "actor_label": orig["actor_label"], "actor_decision": orig["actor_decision"], "recorded_at": now.Format(time.RFC3339Nano), "reviewer_name": q["reviewer_name"], "reviewer_role": q["reviewer_role"], "simulated": true})
	writeJSON(w, 200, map[string]any{"receipt_ref": next["receipt_id"], "supersedes": orig["receipt_id"], "receipt": next, "event": event})
}

func (s *Server) receiptsHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := append([]map[string]any(nil), state.receipts...)
	state.mu.Unlock()
	for i, j := 0, len(rows)-1; i < j; i, j = i+1, j-1 {
		rows[i], rows[j] = rows[j], rows[i]
	}
	sup := []string{}
	for _, x := range rows {
		if v := str(x["supersedes_receipt"]); v != "" {
			sup = append(sup, v)
		}
	}
	writeJSON(w, 200, map[string]any{"receipts": rows, "total": len(rows), "superseded": uniqueStrings(sup)})
}

func (s *Server) receiptHTTP(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("receipt_id")
	if x := s.findReceipt(id); x != nil {
		writeJSON(w, 200, x)
		return
	}
	writeJSON(w, 404, map[string]any{"detail": "no such receipt"})
}

func (s *Server) ledgerVerifyHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := append([]map[string]any(nil), state.receipts...)
	state.mu.Unlock()
	results := []any{}
	valid, fresh := 0, 0
	for _, x := range rows {
		rep := s.verifyReceipt(x)
		results = append(results, rep)
		if boolv(rep["integrity_verified"]) {
			valid++
		}
		if boolv(rep["fresh"]) {
			fresh++
		}
	}
	writeJSON(w, 200, map[string]any{"total": len(rows), "valid": valid, "invalid": len(rows) - valid, "all_valid": valid == len(rows), "intact": valid, "fresh": fresh, "past_purchase_authority_window": len(rows) - fresh, "results": results, "note": "Ledger health separates cryptographic integrity from the purchase-authority validity window."})
}

func loadPortableSigner(root string) error {
	path := filepath.Join(root, "demo_runtime_seed", "signer_key.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read demo signer: %w", err)
	}
	var payload map[string]string
	if err := json.Unmarshal(raw, &payload); err != nil {
		return fmt.Errorf("decode demo signer: %w", err)
	}
	hexSeed := payload["ramify:demo:signer:receipt"]
	seed, err := hex.DecodeString(hexSeed)
	if err != nil || len(seed) != ed25519.SeedSize {
		return fmt.Errorf("demo signer seed is invalid")
	}
	priv := ed25519.NewKeyFromSeed(seed)
	state.mu.Lock()
	state.priv = priv
	state.pub = priv.Public().(ed25519.PublicKey)
	state.mu.Unlock()
	return nil
}

func (s *Server) RuntimeDir() string {
	path := filepath.Join(s.root, "runtime_data")
	_ = os.MkdirAll(path, 0o700)
	return path
}

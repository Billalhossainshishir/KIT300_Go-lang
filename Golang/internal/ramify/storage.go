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
	return &runtimeState{
		receipts: make([]map[string]any, 0), actions: make([]map[string]any, 0), cart: make([]map[string]any, 0),
		orders: make([]map[string]any, 0), requisitions: make([]map[string]any, 0), customAgents: map[string]map[string]any{},
		pub: pub, priv: priv,
	}
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

func eventHash(event map[string]any) string {
	payload := copyMap(event)
	delete(payload, "event_hash")
	b, _ := json.Marshal(payload)
	h := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(h[:])
}

func appendActionLocked(event map[string]any) map[string]any {
	event = copyMap(event)
	event["event_sequence"] = len(state.actions) + 1
	prev := "GENESIS"
	if len(state.actions) > 0 {
		prev = str(state.actions[len(state.actions)-1]["event_hash"])
	}
	event["previous_event_hash"] = prev
	event["event_hash"] = eventHash(event)
	state.actions = append(state.actions, event)
	return copyMap(event)
}

func (s *Server) addAction(event map[string]any) map[string]any {
	state.mu.Lock()
	out := appendActionLocked(event)
	state.mu.Unlock()
	_ = s.persistActions()
	return out
}

func (s *Server) addActionOnce(event map[string]any) (map[string]any, bool) {
	ref, action := str(event["receipt_ref"]), str(event["action"])
	state.mu.Lock()
	for i := len(state.actions) - 1; i >= 0; i-- {
		row := state.actions[i]
		if str(row["receipt_ref"]) == ref && str(row["action"]) == action {
			out := copyMap(row)
			state.mu.Unlock()
			return out, false
		}
	}
	out := appendActionLocked(event)
	state.mu.Unlock()
	_ = s.persistActions()
	return out, true
}

func actionCountFor(receiptID string) int {
	state.mu.Lock()
	defer state.mu.Unlock()
	n := 0
	for _, row := range state.actions {
		if str(row["receipt_ref"]) == receiptID {
			n++
		}
	}
	return n
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
	permitted := append([]string{}, stringSlice(receipt["permitted_actions"])...)
	for _, x := range stringSlice(receipt["human_authorised_actions"]) {
		if !contains(permitted, x) {
			permitted = append(permitted, x)
		}
	}
	act := str(q["action"])
	if !contains(permitted, act) {
		writeJSON(w, 409, map[string]any{"detail": fmt.Sprintf("The decision was %s, which does not permit %s.", str(receipt["actor_decision"]), act)})
		return
	}
	e, created := s.addActionOnce(map[string]any{
		"event_id": "ramify:demo:act:" + randomHex(16), "action": act, "receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"],
		"subject_ref": receipt["subject_ref"], "product_name": valueOr(receipt, "product_name", ""), "actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"],
		"actor_decision": receipt["actor_decision"], "recorded_at": rfc3339Nano(time.Now().UTC()), "simulated": true,
		"notice": "Simulated. Nothing was purchased and no money moved.",
	})
	writeJSON(w, 200, map[string]any{"event": e, "events_for_receipt": actionCountFor(str(receipt["receipt_id"])), "already_recorded": !created})
}

func (s *Server) actionsHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := cloneRows(state.actions)
	state.mu.Unlock()
	for i, j := 0, len(rows)-1; i < j; i, j = i+1, j-1 {
		rows[i], rows[j] = rows[j], rows[i]
	}
	writeJSON(w, 200, map[string]any{"events": rows})
}

func (s *Server) actionsVerifyHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := cloneRows(state.actions)
	state.mu.Unlock()
	expectedPrev := "GENESIS"
	problems := []any{}
	for i, row := range rows {
		seq := i + 1
		if intv(row["event_sequence"]) != seq {
			problems = append(problems, map[string]any{"sequence": seq, "problem": "event_sequence mismatch"})
		}
		if str(row["previous_event_hash"]) != expectedPrev {
			problems = append(problems, map[string]any{"sequence": seq, "problem": "previous_event_hash mismatch"})
		}
		if str(row["event_hash"]) != eventHash(row) {
			problems = append(problems, map[string]any{"sequence": seq, "problem": "event_hash mismatch"})
		}
		ref := str(row["receipt_ref"])
		if ref == "" {
			problems = append(problems, map[string]any{"sequence": seq, "problem": "event has no receipt_ref"})
		} else if receipt := s.findReceipt(ref); receipt == nil {
			problems = append(problems, map[string]any{"sequence": seq, "problem": "receipt_ref missing from receipt ledger"})
		} else {
			if str(receipt["payload_hash"]) != str(row["receipt_hash"]) {
				problems = append(problems, map[string]any{"sequence": seq, "problem": "receipt_hash does not match linked receipt"})
			}
			if !boolv(s.verifyReceipt(receipt)["integrity_verified"]) {
				problems = append(problems, map[string]any{"sequence": seq, "problem": "linked receipt integrity does not verify"})
			}
		}
		expectedPrev = str(row["event_hash"])
	}
	writeJSON(w, 200, map[string]any{
		"total": len(rows), "valid": len(problems) == 0, "problems": problems,
		"head_hash": func() string {
			if len(rows) == 0 {
				return "GENESIS"
			}
			return expectedPrev
		}(),
		"note": "SHA-256 hash-linked local demonstration ledger with receipt-link verification; not a distributed immutable log.",
	})
}

func (s *Server) reviewQueueHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := cloneRows(state.receipts)
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
	// newest first, matching FastAPI
	for i, j := 0, len(open)-1; i < j; i, j = i+1, j-1 {
		open[i], open[j] = open[j], open[i]
	}
	for i, j := 0, len(resolved)-1; i < j; i, j = i+1, j-1 {
		resolved[i], resolved[j] = resolved[j], resolved[i]
	}
	if len(resolved) > 20 {
		resolved = resolved[:20]
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
	if orig["supersedes_receipt"] != nil || orig["human_review"] != nil {
		writeJSON(w, 409, map[string]any{"detail": "A human-review successor is terminal and cannot be reviewed again to mint fresh transaction authority. Run a new product assessment if a new decision is required."})
		return
	}
	d := str(orig["actor_decision"])
	if d != "hold" && d != "escalate" {
		writeJSON(w, 409, map[string]any{"detail": "This decision does not require human review."})
		return
	}
	if s.hasSuccessor(str(orig["receipt_id"])) {
		writeJSON(w, 409, map[string]any{"detail": "This review has already been answered. The original receipt remains unchanged."})
		return
	}
	if !boolv(s.verifyReceipt(orig)["purchase_authority_valid"]) {
		writeJSON(w, 409, map[string]any{"detail": "This review request is no longer current and intact. Run the product check again."})
		return
	}

	next := copyMap(orig)
	delete(next, "payload_hash")
	delete(next, "signature")
	next["receipt_id"] = "ramify:demo:rcpt:" + randomHex(16)
	next["supersedes_receipt"] = orig["receipt_id"]
	now := time.Now().UTC()
	reviewedAt := rfc3339Nano(now)
	next["timestamp"] = reviewedAt
	next["expires_at"] = rfc3339Nano(now.Add(time.Hour))
	outcome := str(q["outcome"])
	label := "Approved once for this simulated transaction"
	consequence := "This successor receipt may admit one simulated basket line. The objective posture and original agent decision remain unchanged."
	if outcome == "confirmed" {
		label = "Declined — leave the item unchanged"
		next["selected_action"] = "halt"
		next["human_authorised_actions"] = []string{}
		consequence = "No basket line or requisition is created, and nothing proceeds."
	} else {
		action := "add_to_mock_cart"
		if p := s.profiles()[str(orig["actor_ref"])]; p != nil && str(p["purchase_style"]) == "requisition" {
			action = "create_mock_requisition"
			consequence = "This successor receipt may create one simulated purchase requisition. The objective posture and original agent decision remain unchanged."
		}
		next["human_authorised_actions"] = []string{action}
		if action == "create_mock_requisition" {
			next["selected_action"] = "human_authorised_requisition"
		} else {
			next["selected_action"] = "human_authorised_purchase"
		}
	}
	next["human_review"] = map[string]any{
		"outcome": outcome, "outcome_label": label, "reviewer_name": q["reviewer_name"], "reviewer_role": q["reviewer_role"], "note": q["reviewer_note"],
		"reviewed_at": reviewedAt, "reviewed_decision": orig["actor_decision"], "decision_scope": "this simulated transaction only",
		"reviewer_attestation": "The named reviewer made this simulated decision. This field is a recorded acknowledgement, not a personal cryptographic signature.",
	}
	meaning := str(orig["objective_posture"])
	if row := standingDisplay(str(obj(orig["status_result"])["standing"])); row != nil {
		_ = row
	}
	presentation := map[string]map[string]string{
		"allow":              {"label": "Approved", "meaning": "Every check passed. The agent may proceed."},
		"allow_with_warning": {"label": "Approved with warning", "meaning": "The agent may proceed, but there is a finding the buyer should see first."},
		"hold":               {"label": "Human review required", "meaning": "The agent stops and a person decides."},
		"escalate":           {"label": "Human review required", "meaning": "Not enough was on file to judge. The agent stops and a person decides."},
		"block":              {"label": "Rejected", "meaning": "A check failed on grounds no policy can soften. The agent must not proceed."},
	}
	if p := presentation[str(orig["objective_posture"])]; p != nil {
		meaning = p["label"] + ". " + p["meaning"]
	}
	next["human_receipt"] = map[string]any{
		"receipt_type": "human_decision_summary", "headline": label,
		"reviewer":                map[string]any{"name": q["reviewer_name"], "role": q["reviewer_role"]},
		"what_ramify_found":       "Objective posture " + str(orig["objective_posture"]) + " — " + meaning,
		"what_the_agent_did":      str(orig["actor_label"]) + " returned " + str(orig["actor_decision"]) + " and handed the decision to a person.",
		"what_the_person_decided": label, "why_it_stopped": valueOr(orig, "primary_reason", "No primary reason recorded."),
		"important_findings": stringSlice(orig["reason_codes"]), "consequence": consequence, "scope": "this simulated transaction only",
		"original_receipt": map[string]any{"receipt_id": orig["receipt_id"], "payload_hash": orig["payload_hash"], "unchanged": true},
		"reviewed_at":      reviewedAt,
		"notice":           "Plain-language summary of the signed machine record. Synthetic demonstration only; no real purchase or approval occurred.",
	}
	next = s.seal(next)
	state.mu.Lock()
	// Atomic duplicate check.
	for _, row := range state.receipts {
		if str(row["supersedes_receipt"]) == str(orig["receipt_id"]) {
			state.mu.Unlock()
			writeJSON(w, 409, map[string]any{"detail": "This review was answered by another request. Refresh Needs me to see it."})
			return
		}
	}
	state.receipts = append(state.receipts, next)
	state.mu.Unlock()
	_ = s.persistReceipts()
	event := s.addAction(map[string]any{
		"event_id": "ramify:demo:act:" + randomHex(16), "action": "human_review_" + outcome, "receipt_ref": next["receipt_id"], "receipt_hash": next["payload_hash"],
		"supersedes_receipt": orig["receipt_id"], "subject_ref": orig["subject_ref"], "product_name": valueOr(orig, "product_name", ""),
		"actor_ref": orig["actor_ref"], "actor_label": orig["actor_label"], "actor_decision": orig["actor_decision"], "recorded_at": reviewedAt,
		"reviewer_name": q["reviewer_name"], "reviewer_role": q["reviewer_role"], "simulated": true,
		"notice": "Human review appended. The original receipt was not changed.",
	})
	writeJSON(w, 200, map[string]any{"receipt_ref": next["receipt_id"], "supersedes": orig["receipt_id"], "receipt": next, "event": event})
}

func (s *Server) receiptsHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	rows := cloneRows(state.receipts)
	state.mu.Unlock()
	for i, j := 0, len(rows)-1; i < j; i, j = i+1, j-1 {
		rows[i], rows[j] = rows[j], rows[i]
	}
	limit := 40
	if len(rows) > limit {
		rows = rows[:limit]
	}
	sup := []string{}
	for _, x := range rows {
		if v := str(x["supersedes_receipt"]); v != "" {
			sup = append(sup, v)
		}
	}
	writeJSON(w, 200, map[string]any{"receipts": rows, "total": func() int { state.mu.Lock(); defer state.mu.Unlock(); return len(state.receipts) }(), "superseded": uniqueStrings(sup)})
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
	rows := cloneRows(state.receipts)
	state.mu.Unlock()
	results := []any{}
	valid, fresh := 0, 0
	for _, x := range rows {
		rep := s.verifyReceipt(x)
		results = append(results, rep)
		if boolv(rep["integrity_verified"]) {
			valid++
		}
		if v, ok := rep["fresh"].(bool); ok && v {
			fresh++
		}
	}
	if len(results) > 20 {
		results = results[len(results)-20:]
	}
	writeJSON(w, 200, map[string]any{
		"total": len(rows), "valid": valid, "invalid": len(rows) - valid, "all_valid": valid == len(rows), "intact": valid, "fresh": fresh,
		"past_purchase_authority_window": len(rows) - fresh, "results": results,
		"note": "Ledger health separates cryptographic integrity from the one-hour purchase-authority validity window. An old receipt can remain unchanged and verifiable as history after it stops being current purchase authority.",
	})
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
	_ = os.MkdirAll(s.runtimeDir, 0o700)
	return s.runtimeDir
}

package ramify

import (
	"fmt"
	"net/http"
	"time"
)

func (s *Server) cartContents() map[string]any {
	state.mu.Lock()
	defer state.mu.Unlock()
	lines := append([]map[string]any(nil), state.cart...)
	items, total := 0, 0
	for _, l := range lines {
		items += intv(l["quantity"])
		total += intv(l["line_total_cents"])
	}
	orders := append([]map[string]any(nil), state.orders...)
	reqs := append([]map[string]any(nil), state.requisitions...)
	return map[string]any{"lines": lines, "line_count": len(lines), "item_count": items, "total_cents": total, "orders": orders, "requisitions": reqs}
}

func (s *Server) cartHTTP(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, s.cartContents())
}

func (s *Server) cartAddByReceipt(id string) (map[string]any, error) {
	receipt := s.findReceipt(id)
	if receipt == nil {
		return nil, fmt.Errorf("That receipt is not in the ledger.")
	}
	if !boolv(s.verifyReceipt(receipt)["purchase_authority_valid"]) {
		return nil, fmt.Errorf("This receipt is no longer valid purchase authority. Run the check again.")
	}
	perm := append(stringSlice(receipt["permitted_actions"]), stringSlice(receipt["human_authorised_actions"])...)
	if !contains(perm, "add_to_mock_cart") && !contains(perm, "purchase_autonomously") {
		return nil, fmt.Errorf("The signed decision does not permit a basket action.")
	}
	o := obj(receipt["order"])
	if o == nil {
		return nil, fmt.Errorf("This receipt carries no complete signed price/quantity values.")
	}
	line := map[string]any{"line_id": randomHex(6), "subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"], "brand": valueOr(s.seed.Subject(str(receipt["subject_ref"])), "brand", ""), "quantity": o["quantity"], "unit_price_cents": o["unit_price_cents"], "line_total_cents": o["line_total_cents"], "receipt_ref": receipt["receipt_id"], "payload_hash": receipt["payload_hash"], "actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"], "objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"], "unattended": str(receipt["selected_action"]) == "purchase_autonomously", "human_authorised": len(stringSlice(receipt["human_authorised_actions"])) > 0, "added_at": time.Now().UTC().Format(time.RFC3339Nano)}
	state.mu.Lock()
	for _, x := range state.cart {
		if str(x["receipt_ref"]) == id {
			state.mu.Unlock()
			return nil, fmt.Errorf("This receipt has already been used for a basket line.")
		}
	}
	state.cart = append(state.cart, line)
	state.mu.Unlock()
	return line, nil
}

func (s *Server) cartAddHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	line, err := s.cartAddByReceipt(str(q["receipt_ref"]))
	if err != nil {
		writeJSON(w, 409, map[string]any{"detail": err.Error()})
		return
	}
	writeJSON(w, 200, map[string]any{"line": line, "cart": s.cartContents()})
}

func (s *Server) requisitionHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	receipt := s.findReceipt(str(q["receipt_ref"]))
	if receipt == nil {
		writeJSON(w, 409, map[string]any{"detail": "That receipt is not in the ledger."})
		return
	}
	perm := append(stringSlice(receipt["permitted_actions"]), stringSlice(receipt["human_authorised_actions"])...)
	if !contains(perm, "create_mock_requisition") {
		writeJSON(w, 409, map[string]any{"detail": "The signed decision does not permit a requisition."})
		return
	}
	o := obj(receipt["order"])
	rec := s.seal(map[string]any{"schema_version": "0.4", "record_type": "requisition_record", "requisition_id": "ramify:demo:req:" + randomHex(16), "data_snapshot": s.seed.SnapshotID(), "subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"], "quantity": o["quantity"], "unit_price_cents": o["unit_price_cents"], "line_total_cents": o["line_total_cents"], "currency": "AUD", "actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"], "objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"], "receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"], "lines": []any{map[string]any{"subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"], "quantity": o["quantity"], "line_total_cents": o["line_total_cents"], "receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"], "actor_ref": receipt["actor_ref"], "objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"]}}, "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "notice": "Synthetic local demonstration requisition only."})
	state.mu.Lock()
	state.requisitions = append(state.requisitions, rec)
	state.mu.Unlock()
	writeJSON(w, 200, map[string]any{"requisition": rec, "cart": s.cartContents()})
}

func (s *Server) cartRemoveHTTP(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("line_id")
	state.mu.Lock()
	before := len(state.cart)
	out := state.cart[:0]
	for _, l := range state.cart {
		if str(l["line_id"]) != id {
			out = append(out, l)
		}
	}
	state.cart = out
	state.mu.Unlock()
	if before == len(out) {
		writeJSON(w, 404, map[string]any{"detail": "no such line"})
		return
	}
	writeJSON(w, 200, s.cartContents())
}

func (s *Server) cartClearHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	state.cart = nil
	state.mu.Unlock()
	writeJSON(w, 200, s.cartContents())
}

func (s *Server) checkoutHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	if len(state.cart) == 0 {
		state.mu.Unlock()
		writeJSON(w, 409, map[string]any{"detail": "The basket is empty."})
		return
	}
	lines := append([]map[string]any(nil), state.cart...)
	state.mu.Unlock()
	total, items := 0, 0
	olines := []any{}
	for _, l := range lines {
		receipt := s.findReceipt(str(l["receipt_ref"]))
		if receipt == nil || !boolv(s.verifyReceipt(receipt)["integrity_verified"]) {
			writeJSON(w, 409, map[string]any{"detail": "A basket line no longer has an intact decision receipt."})
			return
		}
		total += intv(l["line_total_cents"])
		items += intv(l["quantity"])
		olines = append(olines, map[string]any{"subject_ref": l["subject_ref"], "product_name": l["product_name"], "quantity": l["quantity"], "line_total_cents": l["line_total_cents"], "receipt_ref": l["receipt_ref"], "receipt_hash": l["payload_hash"], "actor_ref": l["actor_ref"], "objective_posture": l["objective_posture"], "actor_decision": l["actor_decision"], "human_authorised": valueOr(l, "human_authorised", false)})
	}
	order := s.seal(map[string]any{"schema_version": "0.4", "record_type": "order_record", "order_id": "ramify:demo:order:" + randomHex(16), "data_snapshot": s.seed.SnapshotID(), "line_count": len(lines), "item_count": items, "total_cents": total, "currency": "AUD", "lines": olines, "timestamp": time.Now().UTC().Format(time.RFC3339Nano), "notice": "Simulated order. No purchase was made, no money moved and no inventory was touched."})
	state.mu.Lock()
	state.orders = append(state.orders, order)
	state.cart = nil
	state.mu.Unlock()
	writeJSON(w, 200, map[string]any{"order": order, "cart": s.cartContents()})
}

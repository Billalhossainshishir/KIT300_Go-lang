package ramify

import (
	"fmt"
	"net/http"
	"time"
)

var basketActions = []string{"add_to_mock_cart", "purchase_autonomously"}

func cloneRows(rows []map[string]any) []map[string]any {
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, copyMap(row))
	}
	return out
}

func (s *Server) cartContents() map[string]any {
	state.mu.Lock()
	defer state.mu.Unlock()
	lines := cloneRows(state.cart)
	items, total := 0, 0
	for _, l := range lines {
		items += intv(l["quantity"])
		total += intv(l["line_total_cents"])
	}
	orders := cloneRows(state.orders)
	reqs := cloneRows(state.requisitions)
	// FastAPI returns newest transaction history first.
	for i, j := 0, len(orders)-1; i < j; i, j = i+1, j-1 {
		orders[i], orders[j] = orders[j], orders[i]
	}
	for i, j := 0, len(reqs)-1; i < j; i, j = i+1, j-1 {
		reqs[i], reqs[j] = reqs[j], reqs[i]
	}
	if len(orders) > 10 {
		orders = orders[:10]
	}
	if len(reqs) > 10 {
		reqs = reqs[:10]
	}
	return map[string]any{
		"lines": lines, "line_count": len(lines), "item_count": items, "total_cents": total,
		"orders": orders, "requisitions": reqs,
	}
}

func (s *Server) cartHTTP(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, s.cartContents())
}

func (s *Server) hasSuccessor(receiptID string) bool {
	state.mu.Lock()
	defer state.mu.Unlock()
	for _, row := range state.receipts {
		if str(row["supersedes_receipt"]) == receiptID {
			return true
		}
	}
	return false
}

func (s *Server) assertReceiptAuthority(receipt map[string]any, requiredAny []string) error {
	if str(receipt["assessment_context"]) != "purchase" {
		return fmt.Errorf("This receipt came from an exploratory/demo check, not an active purchase journey.")
	}
	report := s.verifyReceipt(receipt)
	if !boolv(report["purchase_authority_valid"]) {
		return fmt.Errorf("This receipt is no longer valid purchase authority. Run the check again.")
	}
	if id := str(receipt["receipt_id"]); id != "" && s.hasSuccessor(id) {
		return fmt.Errorf("This receipt has been superseded by a later decision and is no longer transaction authority.")
	}
	if len(requiredAny) > 0 {
		permitted := append([]string{}, stringSlice(receipt["permitted_actions"])...)
		for _, x := range stringSlice(receipt["human_authorised_actions"]) {
			if !contains(permitted, x) {
				permitted = append(permitted, x)
			}
		}
		ok := false
		for _, required := range requiredAny {
			if contains(permitted, required) {
				ok = true
				break
			}
		}
		if !ok {
			return fmt.Errorf("The signed decision was %s and does not permit the requested transaction path.", str(receipt["actor_decision"]))
		}
	}
	return nil
}

func receiptAlreadyUsed(receiptID string) bool {
	for _, x := range state.cart {
		if str(x["receipt_ref"]) == receiptID {
			return true
		}
	}
	for _, order := range state.orders {
		for _, lineRaw := range arr(order["lines"]) {
			if str(obj(lineRaw)["receipt_ref"]) == receiptID {
				return true
			}
		}
	}
	for _, req := range state.requisitions {
		if str(req["receipt_ref"]) == receiptID {
			return true
		}
		for _, lineRaw := range arr(req["lines"]) {
			if str(obj(lineRaw)["receipt_ref"]) == receiptID {
				return true
			}
		}
	}
	return false
}

func (s *Server) recordTransactionAction(receipt map[string]any, action string) {
	_, _ = s.addActionOnce(map[string]any{
		"event_id": "ramify:demo:act:" + randomHex(16), "action": action, "receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"],
		"subject_ref": receipt["subject_ref"], "product_name": valueOr(receipt, "product_name", ""), "actor_ref": receipt["actor_ref"],
		"actor_label": receipt["actor_label"], "actor_decision": receipt["actor_decision"], "recorded_at": rfc3339Nano(time.Now().UTC()),
		"simulated": true, "notice": "Simulated transaction step recorded. No money or inventory moved.",
	})
}

func (s *Server) cartAddByReceipt(id string) (map[string]any, error) {
	receipt := s.findReceipt(id)
	if receipt == nil {
		return nil, fmt.Errorf("That receipt is not in the ledger.")
	}
	if err := s.assertReceiptAuthority(receipt, basketActions); err != nil {
		return nil, err
	}
	o := obj(receipt["order"])
	if o == nil || o["quantity"] == nil || o["unit_price_cents"] == nil || o["line_total_cents"] == nil {
		return nil, fmt.Errorf("This receipt carries no complete signed price/quantity values, so it cannot enter the basket.")
	}
	qty, unit, total := intv(o["quantity"]), intv(o["unit_price_cents"]), intv(o["line_total_cents"])
	if qty < 1 || unit < 0 || total != unit*qty {
		return nil, fmt.Errorf("The signed order values are internally inconsistent.")
	}
	humanReview := obj(receipt["human_review"])
	line := map[string]any{
		"line_id": randomHex(6), "subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"],
		"brand": valueOr(s.seed.Subject(str(receipt["subject_ref"])), "brand", ""), "quantity": qty,
		"unit_price_cents": unit, "line_total_cents": total, "receipt_ref": receipt["receipt_id"], "payload_hash": receipt["payload_hash"],
		"actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"], "objective_posture": receipt["objective_posture"],
		"actor_decision": receipt["actor_decision"], "unattended": str(receipt["selected_action"]) == "purchase_autonomously",
		"human_authorised":     len(stringSlice(receipt["human_authorised_actions"])) > 0,
		"human_review_outcome": valueOr(humanReview, "outcome", nil), "supersedes_receipt": valueOr(receipt, "supersedes_receipt", nil),
		"added_at": rfc3339Nano(time.Now().UTC()),
	}
	state.mu.Lock()
	if receiptAlreadyUsed(id) {
		state.mu.Unlock()
		return nil, fmt.Errorf("This receipt has already been used for a basket/order line. Run the check again for a new transaction.")
	}
	state.cart = append(state.cart, line)
	state.mu.Unlock()
	_ = s.persistCart()
	action := "add_to_mock_cart"
	if str(receipt["selected_action"]) == "purchase_autonomously" {
		action = "purchase_autonomously"
	}
	s.recordTransactionAction(receipt, action)
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
	if err := s.assertReceiptAuthority(receipt, []string{"create_mock_requisition"}); err != nil {
		writeJSON(w, 409, map[string]any{"detail": err.Error()})
		return
	}
	o := obj(receipt["order"])
	if o == nil || o["quantity"] == nil || o["unit_price_cents"] == nil || o["line_total_cents"] == nil {
		writeJSON(w, 409, map[string]any{"detail": "This receipt carries no complete signed price/quantity values."})
		return
	}
	id := str(receipt["receipt_id"])
	state.mu.Lock()
	if receiptAlreadyUsed(id) {
		state.mu.Unlock()
		writeJSON(w, 409, map[string]any{"detail": "This receipt has already been used for a basket, order or requisition. Run the check again for a new transaction."})
		return
	}
	state.mu.Unlock()

	now := time.Now().UTC()
	line := map[string]any{
		"subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"], "quantity": o["quantity"],
		"line_total_cents": o["line_total_cents"], "receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"],
		"actor_ref": receipt["actor_ref"], "objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"],
		"human_authorised": len(stringSlice(receipt["human_authorised_actions"])) > 0, "supersedes_receipt": valueOr(receipt, "supersedes_receipt", nil),
	}
	rec := s.seal(map[string]any{
		"schema_version": "0.4", "record_type": "requisition_record", "requisition_id": "ramify:demo:req:" + randomHex(16),
		"data_snapshot": s.seed.SnapshotID(), "subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"],
		"quantity": o["quantity"], "unit_price_cents": o["unit_price_cents"], "line_total_cents": o["line_total_cents"], "currency": "AUD",
		"actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"], "objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"],
		"receipt_ref": receipt["receipt_id"], "receipt_hash": receipt["payload_hash"], "lines": []any{line}, "timestamp": rfc3339Nano(now),
		"customer_summary": map[string]any{
			"headline":            "RAMIFY recorded a simulated purchase requisition.",
			"authority":           "The requisition is linked to the signed product decision that permitted it.",
			"what_did_not_happen": "No purchase, payment, approval workflow or inventory movement occurred.",
		},
		"notice": "Synthetic local demonstration requisition only. No external procurement system was contacted.",
	})
	state.mu.Lock()
	state.requisitions = append(state.requisitions, rec)
	state.mu.Unlock()
	_ = s.persistCart()
	s.recordTransactionAction(receipt, "create_mock_requisition")
	writeJSON(w, 200, map[string]any{"requisition": rec, "cart": s.cartContents()})
}

func (s *Server) cartRemoveHTTP(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("line_id")
	state.mu.Lock()
	before := len(state.cart)
	out := make([]map[string]any, 0, before)
	for _, l := range state.cart {
		if str(l["line_id"]) != id {
			out = append(out, l)
		}
	}
	state.cart = out
	state.mu.Unlock()
	_ = s.persistCart()
	if before == len(out) {
		writeJSON(w, 404, map[string]any{"detail": "no such line"})
		return
	}
	writeJSON(w, 200, s.cartContents())
}

func (s *Server) cartClearHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	state.cart = make([]map[string]any, 0)
	state.mu.Unlock()
	_ = s.persistCart()
	writeJSON(w, 200, s.cartContents())
}

func (s *Server) checkoutHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	if len(state.cart) == 0 {
		state.mu.Unlock()
		writeJSON(w, 409, map[string]any{"detail": "The basket is empty."})
		return
	}
	lines := cloneRows(state.cart)
	state.mu.Unlock()

	total, items := 0, 0
	olines := make([]any, 0, len(lines))
	humanCount, unattendedCount := 0, 0
	for _, l := range lines {
		receipt := s.findReceipt(str(l["receipt_ref"]))
		if receipt == nil {
			writeJSON(w, 409, map[string]any{"detail": "A basket line no longer has its decision receipt."})
			return
		}
		if err := s.assertReceiptAuthority(receipt, basketActions); err != nil {
			writeJSON(w, 409, map[string]any{"detail": err.Error()})
			return
		}
		if str(receipt["payload_hash"]) != str(l["payload_hash"]) {
			writeJSON(w, 409, map[string]any{"detail": "A basket line no longer matches the receipt that admitted it."})
			return
		}
		o := obj(receipt["order"])
		if str(l["subject_ref"]) != str(receipt["subject_ref"]) || intv(l["quantity"]) != intv(o["quantity"]) || intv(l["line_total_cents"]) != intv(o["line_total_cents"]) {
			writeJSON(w, 409, map[string]any{"detail": "A basket line no longer matches its signed receipt."})
			return
		}
		total += intv(l["line_total_cents"])
		items += intv(l["quantity"])
		if boolv(l["human_authorised"]) {
			humanCount++
		}
		if boolv(l["unattended"]) {
			unattendedCount++
		}
		olines = append(olines, map[string]any{
			"subject_ref": l["subject_ref"], "product_name": l["product_name"], "quantity": l["quantity"], "line_total_cents": l["line_total_cents"],
			"receipt_ref": l["receipt_ref"], "receipt_hash": l["payload_hash"], "actor_ref": l["actor_ref"], "objective_posture": l["objective_posture"],
			"actor_decision": l["actor_decision"], "human_authorised": boolv(l["human_authorised"]), "supersedes_receipt": valueOr(l, "supersedes_receipt", nil),
		})
	}
	normalCount := len(lines) - humanCount - unattendedCount
	order := s.seal(map[string]any{
		"schema_version": "0.4", "record_type": "order_record", "order_id": "ramify:demo:order:" + randomHex(16), "data_snapshot": s.seed.SnapshotID(),
		"line_count": len(lines), "item_count": items, "total_cents": total, "currency": "AUD", "lines": olines, "timestamp": rfc3339Nano(time.Now().UTC()),
		"customer_summary": map[string]any{
			"headline":                     "RAMIFY checked every item before this simulated order was recorded.",
			"what_was_checked":             fmt.Sprintf("%d basket line(s), each linked to a sealed product decision receipt.", len(lines)),
			"how_the_order_was_authorised": fmt.Sprintf("%d line(s) were authorised by a person; %d line(s) were permitted for autonomous purchase; %d line(s) followed the agent's normal purchase policy.", humanCount, unattendedCount, normalCount),
			"what_did_not_happen":          "No real payment, inventory movement or shipment occurred.",
			"audit_message":                "The machine decision, any human follow-on decision and this order record remain separate, linked and independently verifiable.",
		},
		"notice": "Simulated order. No purchase was made, no money moved and no inventory was touched. Every line names the decision receipt that admitted it.",
	})
	state.mu.Lock()
	state.orders = append(state.orders, order)
	state.cart = make([]map[string]any, 0)
	state.mu.Unlock()
	_ = s.persistCart()
	writeJSON(w, 200, map[string]any{"order": order, "cart": s.cartContents()})
}

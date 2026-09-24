package ramify

import (
	"fmt"
	"time"
)

func (s *Server) actionSelect(decision string, p map[string]any, subject map[string]any) map[string]any {
	permitted := stringSlice(obj(p["permitted_actions"])[decision])
	selected := "halt"
	auto := contains(stringSlice(p["auto_purchase_on"]), decision) && str(p["purchase_style"]) != "requisition"
	if auto && contains(permitted, "purchase_autonomously") {
		selected = "purchase_autonomously"
	} else {
		prefs := map[string][]string{"allow": {"add_to_mock_cart", "create_mock_requisition"}, "allow_with_warning": {"add_to_mock_cart", "create_review_task"}, "hold": {"create_review_task"}, "escalate": {"create_review_task"}, "block": {"halt"}}[decision]
		for _, x := range prefs {
			if contains(permitted, x) {
				selected = x
				break
			}
		}
		if selected == "halt" && len(permitted) > 0 {
			selected = permitted[0]
		}
	}
	out := map[string]any{"decision": decision, "selected_action": selected, "selected_action_description": map[string]string{"purchase_autonomously": "Complete the purchase with no person involved. Simulated.", "add_to_mock_cart": "Add to a simulated cart for a person to confirm.", "create_mock_requisition": "Raise a simulated purchase requisition.", "compare_alternatives": "Offer the buyer a different product.", "create_review_task": "Route to a person and pause until they decide.", "halt": "Stop. Take no further automated action."}[selected], "permitted_actions": permitted, "unattended": selected == "purchase_autonomously", "requires_human": decision == "hold" || decision == "escalate", "simulated": true}
	if replacement := str(subject["superseded_by"]); replacement != "" && contains(permitted, "compare_alternatives") {
		r := s.seed.Subject(replacement)
		out["substitution"] = map[string]any{"superseded_by": replacement, "replacement_name": valueOr(r, "name", replacement), "note": valueOr(subject, "supersession_note", ""), "reason_code": "superseded_product_available", "offered_action": "compare_alternatives"}
	}
	return out
}

func traffic(posture string) map[string]any {
	m := map[string]map[string]any{"allow": {"colour": "green", "label": "Approved", "meaning": "Every check passed. The agent may proceed.", "warning": false, "machine_posture": "allow"}, "allow_with_warning": {"colour": "orange", "label": "Approved with warning", "meaning": "The agent may proceed, but there is a finding the buyer should see first.", "warning": true, "machine_posture": "allow_with_warning"}, "hold": {"colour": "orange", "label": "Human review required", "meaning": "The agent stops and a person decides.", "warning": false, "machine_posture": "hold"}, "escalate": {"colour": "orange", "label": "Human review required", "meaning": "Not enough was on file to judge. The agent stops and a person decides.", "warning": false, "machine_posture": "escalate"}, "block": {"colour": "red", "label": "Rejected", "meaning": "A check failed on grounds no policy can soften. The agent must not proceed.", "warning": false, "machine_posture": "block"}}
	x := copyMap(m[posture])
	x["mapping_version"] = "posture_mapping_v1.0.0"
	return x
}

func (s *Server) assessOne(identifier, actorRef, policyRef string, quantity int, context string, persist bool) (map[string]any, error) {
	if quantity < 1 || quantity > 1000 {
		return nil, fmt.Errorf("quantity must be between 1 and 1000")
	}
	id := s.identifyResult(identifier)
	ref := str(id["subject_ref"])
	if ref == "" {
		ref = identifier
	}
	subject := s.seed.Subject(ref)
	resolve := map[string]any{"subject_ref": ref, "canonical_state": "observed", "known": false}
	if subject != nil {
		resolve = map[string]any{"subject_ref": ref, "canonical_state": "asserted", "product_name": subject["name"], "brand": subject["brand"], "category": subject["category"], "seller_ref": subject["seller_ref"], "identifiers": subject["identifiers"], "known": true}
		if len(arr(subject["claims"])) == 0 {
			resolve["canonical_state"] = "observed"
		}
	}
	status := s.statusResult(ref)
	verify := s.ratify(ref, id, status)
	pack := s.policyPack()
	if policyRef != "" && policyRef != str(pack["policy_ref"]) {
		return nil, fmt.Errorf("Unsupported policy_ref: %s", policyRef)
	}
	checks := []map[string]any{}
	for _, v := range arr(verify["check_results"]) {
		checks = append(checks, obj(v))
	}
	post, matchedRule, primaryRule, primaryReason, matched, reasons := s.objective(checks, str(status["standing"]))
	unit := s.price(ref)
	var line any = nil
	if unit > 0 {
		line = unit * quantity
	}
	order := map[string]any{"quantity": quantity, "unit_price_cents": nil, "line_total_cents": nil}
	if unit > 0 {
		order["unit_price_cents"] = unit
		order["line_total_cents"] = line
	}
	actor, err := s.applyActor(post, actorRef, subject, order)
	if err != nil {
		return nil, err
	}
	reasons = append(reasons, stringSlice(actor["reason_codes"])...)
	a := s.actionSelect(str(actor["decision"]), obj(actor["profile"]), subject)
	if sub := obj(a["substitution"]); sub != nil {
		reasons = append(reasons, str(sub["reason_code"]))
	}
	reasons = uniqueStrings(reasons)
	now := time.Now().UTC()
	receipt := map[string]any{"schema_version": "0.4", "receipt_id": "ramify:demo:rcpt:" + randomHex(16), "subject_ref": ref, "product_name": valueOr(resolve, "product_name", valueOr(id, "product_name", "")), "data_snapshot": s.seed.SnapshotID(), "dataset_digest": verify["dataset_digest"], "assessment_context": context, "policy_ref": pack["policy_ref"], "policy_digest": verify["policy_digest"], "policy_version": pack["policy_version"], "policy_status": pack["status"], "actor_ref": actorRef, "actor_label": actor["actor_label"], "canonical_state": resolve["canonical_state"], "check_results": verify["check_results"], "claim_results": verify["claim_results"], "status_result": status, "objective_posture": post, "objective_matched_rule": matchedRule, "primary_reason_rule": primaryRule, "primary_reason": primaryReason, "matched_conditions": matched, "actor_decision": actor["decision"], "actor_narrowed": actor["narrowed"], "actor_applied_rules": actor["applied_rules"], "actor_conditions": actor["conditions_evaluated"], "reason_codes": reasons, "permitted_actions": a["permitted_actions"], "selected_action": a["selected_action"], "issuer_refs": s.issuerRefs(verify, status), "timestamp": now.Format(time.RFC3339Nano), "expires_at": now.Add(time.Hour).Format(time.RFC3339Nano), "latencies_us": map[string]any{"identify": 1, "resolve": 1, "status": 1, "verify": 1, "assess": 1, "total": 5}, "notice": "Synthetic demonstration data. This receipt records what was checked against a curated test dataset and certifies nothing in the real world."}
	if unit > 0 {
		receipt["order"] = map[string]any{"quantity": quantity, "unit_price_cents": unit, "line_total_cents": unit * quantity, "currency": "AUD"}
	}
	if sub := a["substitution"]; sub != nil {
		receipt["substitution"] = sub
	}
	receipt = s.seal(receipt)
	if persist {
		state.mu.Lock()
		state.receipts = append(state.receipts, receipt)
		state.mu.Unlock()
	}
	out := map[string]any{"subject_ref": ref, "product_name": receipt["product_name"], "resolved": id["resolved"], "objective_posture": post, "objective_light": traffic(post), "actor_decision": actor["decision"], "actor_label": actor["actor_label"], "narrowed": actor["narrowed"], "traffic_light": traffic(str(actor["decision"])), "conditions_evaluated": actor["conditions_evaluated"], "applied_rules": actor["applied_rules"], "reason_codes": reasons, "selected_action": a["selected_action"], "selected_action_description": a["selected_action_description"], "permitted_actions": a["permitted_actions"], "unattended": a["unattended"], "requires_human": a["requires_human"], "escalation": nil, "standing_display": standingDisplay(str(status["standing"])), "primary_reason": primaryReason, "can_add_to_cart": contains(stringSlice(a["permitted_actions"]), "add_to_mock_cart") || contains(stringSlice(a["permitted_actions"]), "purchase_autonomously"), "can_create_requisition": contains(stringSlice(a["permitted_actions"]), "create_mock_requisition"), "substitution": a["substitution"], "order": order, "receipt_ref": receipt["receipt_id"], "receipt": receipt, "call_trace": []any{}, "runtime_timing_ms": map[string]any{"deterministic_evaluation": 0.005, "receipt_build_and_sign": 0.1, "receipt_persistence": 0.01, "full_engine_call": 0.2, "scope_note": "Full HTTP/network/browser time is outside this engine measurement."}, "display_latency_ms": map[string]any{"total": 0.005}}
	if str(actor["decision"]) == "hold" || str(actor["decision"]) == "escalate" || str(actor["decision"]) == "block" {
		out["escalation"] = map[string]any{"kind": "review", "headline": "RAMIFY stopped before acting", "body": primaryReason, "decided_by": "A person", "tone": "caution", "icon": "◇", "matched_reason_codes": reasons, "requires_human": boolv(a["requires_human"]), "decision": actor["decision"]}
	}
	return out, nil
}

func standingDisplay(s string) map[string]any {
	return map[string]map[string]any{"no_active_recall": {"user_facing": "No recall or advisory", "light": "green"}, "advisory": {"user_facing": "Under advisory", "light": "amber"}, "recalled": {"user_facing": "Recalled", "light": "red"}, "unknown": {"user_facing": "No standing record held", "light": "amber"}}[s]
}

func (s *Server) issuerRefs(verify, status map[string]any) []string {
	refs := []string{}
	for _, cv := range arr(verify["claim_results"]) {
		refs = append(refs, str(obj(cv)["issuer_ref"]))
	}
	refs = append(refs, str(status["issuer_ref"]))
	return uniqueStrings(refs)
}

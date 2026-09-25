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

func maxUS(d time.Duration) int64 {
	us := d.Microseconds()
	if us < 1 {
		return 1
	}
	return us
}

func msFromUS(us int64) float64 { return float64(us) / 1000.0 }

func (s *Server) assessOne(identifier, actorRef, policyRef string, quantity int, context string, persist bool) (map[string]any, error) {
	if quantity < 1 || quantity > 1000 {
		return nil, fmt.Errorf("quantity must be between 1 and 1000")
	}
	fullStarted := time.Now()
	latencies := map[string]int64{}
	trace := []any{}

	started := time.Now()
	id := s.identifyResult(identifier)
	latencies["identify"] = maxUS(time.Since(started))
	ref := str(id["subject_ref"])
	if ref == "" {
		ref = identifier
	}
	identifyOut := ref
	if !boolv(id["resolved"]) {
		identifyOut = "unresolved"
	}
	trace = append(trace, map[string]any{"primitive": "identify", "input": identifier, "output": identifyOut, "latency_us": latencies["identify"]})

	started = time.Now()
	subject := s.seed.Subject(ref)
	resolve := map[string]any{"subject_ref": ref, "canonical_state": "observed", "identifiers": map[string]any{}, "freshness": map[string]any{"generated_at": rfc3339Nano(time.Now().UTC()), "ttl_seconds": freshnessTTLSeconds, "data_snapshot": s.seed.SnapshotID()}, "known": false}
	if subject != nil {
		stateName := "asserted"
		if len(arr(subject["claims"])) == 0 {
			stateName = "observed"
		}
		resolve = map[string]any{
			"subject_ref": ref, "canonical_state": stateName, "product_name": subject["name"], "brand": subject["brand"], "category": subject["category"],
			"seller_ref": subject["seller_ref"], "identifiers": subject["identifiers"], "freshness": map[string]any{"generated_at": rfc3339Nano(time.Now().UTC()), "ttl_seconds": freshnessTTLSeconds, "data_snapshot": s.seed.SnapshotID()}, "known": true,
		}
		for _, key := range []string{"batch_ref", "superseded_by", "supersedes"} {
			if v, ok := subject[key]; ok {
				resolve[key] = v
			}
		}
		if _, ok := subject["superseded_by"]; ok {
			resolve["supersession_note"] = valueOr(subject, "supersession_note", "")
		}
	}
	latencies["resolve"] = maxUS(time.Since(started))
	trace = append(trace, map[string]any{"primitive": "resolve", "input": ref, "output": resolve["canonical_state"], "latency_us": latencies["resolve"]})

	started = time.Now()
	status := s.statusResult(ref)
	latencies["status"] = maxUS(time.Since(started))
	trace = append(trace, map[string]any{"primitive": "status", "input": ref, "output": status["standing"], "latency_us": latencies["status"]})

	started = time.Now()
	verify := s.ratify(ref, id, status)
	latencies["verify"] = maxUS(time.Since(started))
	pack := s.policyPack()
	if policyRef != "" && policyRef != str(pack["policy_ref"]) {
		return nil, fmt.Errorf("Unsupported policy_ref: %s", policyRef)
	}
	checks := []map[string]any{}
	findings := 0
	for _, v := range arr(verify["check_results"]) {
		c := obj(v)
		checks = append(checks, c)
		if str(c["outcome"]) != "pass" {
			findings++
		}
	}
	verifyOut := "all checks passed"
	if findings > 0 {
		verifyOut = fmt.Sprintf("%d finding(s)", findings)
	}
	trace = append(trace, map[string]any{"primitive": "verify", "input": fmt.Sprintf("%d checks", len(checks)), "output": verifyOut, "latency_us": latencies["verify"]})

	unit := s.price(ref)
	order := map[string]any{"quantity": quantity, "unit_price_cents": nil, "line_total_cents": nil}
	if unit > 0 {
		order["unit_price_cents"] = unit
		order["line_total_cents"] = unit * quantity
	}

	started = time.Now()
	post, matchedRule, primaryRule, primaryReason, matched, reasons := s.objective(checks, str(status["standing"]))
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
	latencies["assess"] = maxUS(time.Since(started))
	trace = append(trace, map[string]any{"primitive": "assess", "input": post + " under " + actorRef, "output": actor["decision"], "latency_us": latencies["assess"]})
	latencies["total"] = latencies["identify"] + latencies["resolve"] + latencies["status"] + latencies["verify"] + latencies["assess"]

	now := time.Now().UTC()
	latencyPayload := map[string]any{}
	for k, v := range latencies {
		latencyPayload[k] = v
	}
	receipt := map[string]any{
		"schema_version": "0.4", "receipt_id": "ramify:demo:rcpt:" + randomHex(16), "subject_ref": ref,
		"product_name": valueOr(resolve, "product_name", valueOr(id, "product_name", "")), "data_snapshot": s.seed.SnapshotID(), "dataset_digest": verify["dataset_digest"],
		"assessment_context": context, "policy_ref": pack["policy_ref"], "policy_digest": verify["policy_digest"], "policy_version": pack["policy_version"], "policy_status": pack["status"],
		"actor_ref": actorRef, "actor_label": actor["actor_label"], "call_trace": trace, "canonical_state": resolve["canonical_state"], "check_results": verify["check_results"],
		"claim_results": verify["claim_results"], "status_result": status, "objective_posture": post, "objective_matched_rule": matchedRule, "primary_reason_rule": primaryRule,
		"primary_reason": primaryReason, "matched_conditions": matched, "actor_decision": actor["decision"], "actor_narrowed": actor["narrowed"], "actor_applied_rules": actor["applied_rules"],
		"actor_conditions": actor["conditions_evaluated"], "reason_codes": reasons, "permitted_actions": a["permitted_actions"], "selected_action": a["selected_action"],
		"issuer_refs": s.issuerRefs(verify, status), "timestamp": rfc3339Nano(now), "expires_at": rfc3339Nano(now.Add(time.Hour)), "latencies_us": latencyPayload,
		"timing_scope": map[string]any{
			"signed_measurement": "deterministic five-primitive evaluation through Action Gate",
			"excludes":           []string{"receipt signing", "receipt persistence", "HTTP/network/rendering"},
			"note":               "Full request timing, when reported, is release evidence outside the signed decision payload.",
		},
		"notice": "Synthetic demonstration data. This receipt records what was checked against a curated test dataset and certifies nothing in the real world.",
	}
	if unit > 0 {
		receipt["order"] = map[string]any{"quantity": quantity, "unit_price_cents": unit, "line_total_cents": unit * quantity, "currency": "AUD"}
	}
	if sub := a["substitution"]; sub != nil {
		receipt["substitution"] = sub
	}

	signStarted := time.Now()
	receipt = s.seal(receipt)
	signingUS := maxUS(time.Since(signStarted))
	persistenceUS := int64(0)
	if persist {
		persistStarted := time.Now()
		state.mu.Lock()
		state.receipts = append(state.receipts, receipt)
		state.mu.Unlock()
		_ = s.persistReceipts()
		persistenceUS = maxUS(time.Since(persistStarted))
	}
	fullUS := maxUS(time.Since(fullStarted))

	out := map[string]any{
		"subject_ref": ref, "product_name": receipt["product_name"], "resolved": id["resolved"], "objective_posture": post, "objective_light": traffic(post),
		"actor_decision": actor["decision"], "actor_label": actor["actor_label"], "narrowed": actor["narrowed"], "traffic_light": traffic(str(actor["decision"])),
		"conditions_evaluated": actor["conditions_evaluated"], "applied_rules": actor["applied_rules"], "reason_codes": reasons, "selected_action": a["selected_action"],
		"selected_action_description": a["selected_action_description"], "permitted_actions": a["permitted_actions"], "unattended": a["unattended"], "requires_human": a["requires_human"],
		"escalation": nil, "standing_display": standingDisplay(str(status["standing"])), "primary_reason": primaryReason,
		"can_add_to_cart":        contains(stringSlice(a["permitted_actions"]), "add_to_mock_cart") || contains(stringSlice(a["permitted_actions"]), "purchase_autonomously"),
		"can_create_requisition": contains(stringSlice(a["permitted_actions"]), "create_mock_requisition"), "substitution": a["substitution"], "order": order,
		"receipt_ref": receipt["receipt_id"], "receipt": receipt, "call_trace": trace,
		"runtime_timing_ms": map[string]any{
			"deterministic_evaluation": msFromUS(latencies["total"]), "receipt_build_and_sign": msFromUS(signingUS), "receipt_persistence": msFromUS(persistenceUS),
			"full_engine_call": msFromUS(fullUS), "scope_note": "Full HTTP/network/browser time is outside this engine measurement.",
		},
		"display_latency_ms": map[string]any{
			"identify": msFromUS(latencies["identify"]), "resolve": msFromUS(latencies["resolve"]), "status": msFromUS(latencies["status"]),
			"verify": msFromUS(latencies["verify"]), "assess": msFromUS(latencies["assess"]), "total": msFromUS(latencies["total"]),
		},
	}
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

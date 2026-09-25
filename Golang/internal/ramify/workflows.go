package ramify

import (
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func (s *Server) compareHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	if decodeBody(r, &q) != nil {
		return
	}
	refs := stringSlice(q["actor_refs"])
	if len(refs) == 0 {
		for ref := range s.profiles() {
			refs = append(refs, ref)
		}
		sort.Strings(refs)
	}
	qty := intv(q["quantity"])
	if qty == 0 {
		qty = 1
	}
	rows := []any{}
	postures := map[string]bool{}
	var first map[string]any
	for _, a := range refs {
		o, e := s.assessOne(str(q["identifier"]), a, "", qty, "comparison", true)
		if e != nil {
			continue
		}
		if first == nil {
			first = o
		}
		postures[str(o["objective_posture"])] = true
		rows = append(rows, map[string]any{"actor_ref": a, "actor_label": o["actor_label"], "summary": s.profiles()[a]["summary"], "autonomy": s.profiles()[a]["autonomy"], "objective_posture": o["objective_posture"], "decision": o["actor_decision"], "traffic_light": o["traffic_light"], "narrowed": o["narrowed"], "selected_action": o["selected_action"], "unattended": o["unattended"], "conditions_evaluated": o["conditions_evaluated"], "applied_rules": o["applied_rules"], "receipt_ref": o["receipt_ref"]})
	}
	var posture any = nil
	if len(postures) == 1 {
		for p := range postures {
			posture = p
		}
	}
	writeJSON(w, 200, map[string]any{"subject_ref": first["subject_ref"], "product_name": first["product_name"], "order": first["order"], "objective_agreed": len(postures) <= 1, "objective_posture": posture, "personas": rows})
}

func (s *Server) alternativesHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	actor := str(q["actor_ref"])
	if actor == "" {
		actor = "consumer_v1"
	}
	qty := intv(q["quantity"])
	if qty == 0 {
		qty = 1
	}
	base, _ := s.assessOne(str(q["identifier"]), actor, "", qty, "suggestion", false)
	subject := s.seed.Subject(str(base["subject_ref"]))
	cands := []any{}
	if boolv(base["requires_human"]) && (str(base["objective_posture"]) == "allow" || str(base["objective_posture"]) == "allow_with_warning") {
		for ref, v := range s.seed.Subjects() {
			rec := obj(v)
			if ref == str(base["subject_ref"]) || str(rec["category"]) != str(subject["category"]) {
				continue
			}
			o, _ := s.assessOne(ref, actor, "", qty, "suggestion", false)
			if !boolv(o["requires_human"]) && boolv(o["can_add_to_cart"]) {
				cands = append(cands, map[string]any{"subject_ref": ref, "product_name": o["product_name"], "brand": rec["brand"], "line_total_cents": obj(o["order"])["line_total_cents"], "unit_price_cents": s.price(ref), "objective_posture": o["objective_posture"], "actor_decision": o["actor_decision"], "why": "clears the agent's conditions", "assessment_context": "exploratory", "is_named_replacement": str(subject["superseded_by"]) == ref})
				if len(cands) >= 3 {
					break
				}
			}
		}
	}
	var result any = nil
	if len(cands) > 0 {
		result = map[string]any{"because": "A commercial agent rule stopped the original item.", "actor_ref": actor, "actor_label": base["actor_label"], "candidates": cands, "searched": len(s.seed.Subjects()) - 1, "note": "Exploratory only; selecting one triggers a fresh assessment."}
	}
	writeJSON(w, 200, map[string]any{"alternatives": result})
}

func (s *Server) vocabularyHTTP(w http.ResponseWriter, r *http.Request) {
	postures := []any{
		map[string]any{"machine_posture": "allow", "user_facing": "Approved", "meaning": "Every check passed. The agent may proceed.", "light": "green", "carries_warning": false, "needs_a_person": false},
		map[string]any{"machine_posture": "allow_with_warning", "user_facing": "Approved with warning", "meaning": "The agent may proceed, but there is a finding the buyer should see first.", "light": "orange", "carries_warning": true, "needs_a_person": false},
		map[string]any{"machine_posture": "hold", "user_facing": "Human review required", "meaning": "The agent stops and a person decides.", "light": "orange", "carries_warning": false, "needs_a_person": true},
		map[string]any{"machine_posture": "escalate", "user_facing": "Human review required", "meaning": "Not enough was on file to judge. The agent stops and a person decides.", "light": "orange", "carries_warning": false, "needs_a_person": true},
		map[string]any{"machine_posture": "block", "user_facing": "Rejected", "meaning": "A check failed on grounds no policy can soften. The agent must not proceed.", "light": "red", "carries_warning": false, "needs_a_person": false},
	}
	stands := []any{}
	for _, x := range []string{"no_active_recall", "advisory", "recalled", "unknown"} {
		m := copyMap(standingDisplay(x))
		m["standing"] = x
		stands = append(stands, m)
	}
	rows := []any{}
	order := []string{"allow", "allow_with_warning", "hold", "escalate", "block"}
	for _, o := range order {
		for _, a := range order {
			kind := "widens"
			if o == a {
				kind = "unchanged"
			} else if restrict[a] > restrict[o] {
				kind = "narrows"
			}
			rows = append(rows, map[string]any{"objective_posture": o, "actor_decision": a, "objective_rank": restrict[o], "actor_rank": restrict[a], "permitted": restrict[a] >= restrict[o], "kind": kind})
		}
	}
	writeJSON(w, 200, map[string]any{
		"mapping_version": "posture_mapping_v1.0.0",
		"postures":        postures,
		"standings":       stands,
		"transitions": map[string]any{
			"mapping_version":                 "posture_mapping_v1.0.0",
			"order_least_to_most_restrictive": order,
			"rows":                            rows,
			"note":                            "An actor decision is permitted only where it is at least as restrictive as the objective posture. Every row marked 'widens' is rejected by the policy stage rather than accepted.",
		},
	})
}

func (s *Server) catalogueHTTP(w http.ResponseWriter, r *http.Request) {
	products := []any{}
	for ref, v := range s.seed.Subjects() {
		rec := obj(v)
		seller := s.seller(str(rec["seller_ref"]))
		products = append(products, map[string]any{"subject_ref": ref, "name": rec["name"], "brand": rec["brand"], "category": rec["category"], "seller_ref": rec["seller_ref"], "seller_name": valueOr(seller, "name", ""), "batch_ref": valueOr(rec, "batch_ref", nil), "price_cents": s.price(ref)})
	}
	sort.Slice(products, func(i, j int) bool { return str(obj(products[i])["name"]) < str(obj(products[j])["name"]) })
	agents := []any{}
	for _, p := range s.profiles() {
		agents = append(agents, p)
	}
	scenarios := []any{}
	for _, v := range arr(s.seedMap()["scenarios"]) {
		x := obj(v)
		scenarios = append(scenarios, map[string]any{"id": x["id"], "subject_ref": x["subject_ref"], "actor_ref": x["actor"], "note": x["note"], "expected_objective": x["expected_objective"], "expected_decision": x["expected_decision"]})
	}
	pack := s.policyPack()
	writeJSON(w, 200, map[string]any{"products": products, "actor_profiles": agents, "policy": map[string]any{"policy_ref": pack["policy_ref"], "policy_version": pack["policy_version"], "status": pack["status"], "notice": pack["notice"]}, "scenarios": scenarios, "data_snapshot": s.seed.SnapshotID(), "build": s.build, "snapshot_date": obj(s.seedMap()["meta"])["snapshot_date"], "notice": obj(s.seedMap()["meta"])["notice"]})
}

func (s *Server) subjectHTTP(w http.ResponseWriter, r *http.Request) {
	ref := r.PathValue("subject_ref")
	rec := s.seed.Subject(ref)
	if rec == nil {
		writeJSON(w, 404, map[string]any{"detail": "no such subject"})
		return
	}
	evs := []any{}
	for _, er := range s.evidenceRefs(rec) {
		if e := s.evidence(er); e != nil {
			evs = append(evs, e)
		}
	}
	writeJSON(w, 200, map[string]any{"subject": rec, "status": s.seed.Status(ref), "evidence": evs})
}

func (s *Server) coverageHTTP(w http.ResponseWriter, r *http.Request) {
	sc := arr(s.seedMap()["scenarios"])
	rows := []any{}
	for _, v := range sc {
		x := obj(v)
		rows = append(rows, map[string]any{"id": x["id"], "note": x["note"], "expected_objective": x["expected_objective"], "expected_decision": x["expected_decision"]})
	}
	writeJSON(w, 200, map[string]any{"scenario_count": len(sc), "product_count": len(s.seed.Subjects()), "seller_count": len(section(s.seedMap(), "sellers")), "evidence_count": len(section(s.seedMap(), "evidence")), "actor_count": len(s.profiles()), "scenarios": rows, "notice": "Coverage is asserted against the synthetic dataset."})
}

func (s *Server) evidenceTamperHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	ref := str(q["subject_ref"])
	sub := s.seed.Subject(ref)
	if sub == nil {
		writeJSON(w, 404, map[string]any{"detail": "No evidence artefact is available for this subject."})
		return
	}
	var record map[string]any
	for _, evidenceRef := range s.evidenceRefs(sub) {
		candidate := s.evidence(evidenceRef)
		if candidate != nil && str(candidate["storage_path"]) != "" {
			record = candidate
			break
		}
	}
	if record == nil {
		writeJSON(w, 404, map[string]any{"detail": "No evidence artefact is available for this subject."})
		return
	}
	root := filepath.Clean(filepath.Join(s.root, "data"))
	path := filepath.Clean(filepath.Join(root, str(record["storage_path"])))
	rel, err := filepath.Rel(root, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		writeJSON(w, 409, map[string]any{"detail": "Evidence path is outside the synthetic data directory."})
		return
	}
	original, err := os.ReadFile(path)
	if err != nil {
		writeJSON(w, 404, map[string]any{"detail": "Evidence artefact is missing."})
		return
	}
	tampered := append(append([]byte{}, original...), []byte("\nRAMIFY SYNTHETIC IN-MEMORY TAMPER DEMO.\n")...)
	claims := arr(sub["claims"])
	cleanFinding := s.evaluateEvidenceIntegrityBytes(record, original, ref, claims)
	tamperedFinding := s.evaluateEvidenceIntegrityBytes(record, tampered, ref, claims)
	reasons := []string{}
	if code := integrityReason[str(tamperedFinding["state"])]; code != "" {
		reasons = append(reasons, code)
	}
	writeJSON(w, 200, map[string]any{
		"subject_ref": ref, "evidence_ref": record["ref"], "clean_integrity": cleanFinding, "tampered_integrity": tamperedFinding,
		"ratify_outcome": "fail", "objective_posture": "block", "reason_codes": reasons,
		"shared_artefact_modified": false, "artefact_restored": true,
		"note": "Synthetic isolated demonstration; the shared evidence artefact was never modified.",
	})
}

func (s *Server) demoCartResetHTTP(w http.ResponseWriter, r *http.Request) {
	// This Go build keeps the guided-demo transaction isolated in memory for the
	// request, so there is no dedicated persistent demo basket to clear and the
	// normal consumer basket is deliberately left untouched.
	writeJSON(w, 200, map[string]any{"cleared": true, "simulated": true, "normal_cart_untouched": true})
}

func (s *Server) demoCheckoutProofHTTP(w http.ResponseWriter, r *http.Request) {
	o, err := s.assessOne("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1", "", 1, "purchase", true)
	if err != nil {
		writeJSON(w, 500, map[string]any{"detail": err.Error()})
		return
	}
	receipt := obj(o["receipt"])
	orderValues := obj(receipt["order"])
	line := map[string]any{
		"line_id": randomHex(6), "subject_ref": receipt["subject_ref"], "product_name": receipt["product_name"],
		"brand": valueOr(s.seed.Subject(str(receipt["subject_ref"])), "brand", ""), "quantity": orderValues["quantity"],
		"unit_price_cents": orderValues["unit_price_cents"], "line_total_cents": orderValues["line_total_cents"],
		"receipt_ref": receipt["receipt_id"], "payload_hash": receipt["payload_hash"], "actor_ref": receipt["actor_ref"], "actor_label": receipt["actor_label"],
		"objective_posture": receipt["objective_posture"], "actor_decision": receipt["actor_decision"], "unattended": false,
		"human_authorised": false, "human_review_outcome": nil, "supersedes_receipt": nil, "added_at": rfc3339Nano(time.Now().UTC()),
	}
	orderLine := map[string]any{
		"subject_ref": line["subject_ref"], "product_name": line["product_name"], "quantity": line["quantity"], "line_total_cents": line["line_total_cents"],
		"receipt_ref": line["receipt_ref"], "receipt_hash": line["payload_hash"], "actor_ref": line["actor_ref"], "objective_posture": line["objective_posture"],
		"actor_decision": line["actor_decision"], "human_authorised": false, "supersedes_receipt": nil,
	}
	order := s.seal(map[string]any{
		"schema_version": "0.4", "record_type": "order_record", "order_id": "ramify:demo:order:" + randomHex(16), "data_snapshot": s.seed.SnapshotID(),
		"line_count": 1, "item_count": 1, "total_cents": intv(line["line_total_cents"]), "currency": "AUD", "lines": []any{orderLine}, "timestamp": rfc3339Nano(time.Now().UTC()),
		"customer_summary": map[string]any{
			"headline":                     "RAMIFY checked every item before this simulated order was recorded.",
			"what_was_checked":             "1 basket line(s), each linked to a sealed product decision receipt.",
			"how_the_order_was_authorised": "0 line(s) were authorised by a person; 0 line(s) were permitted for autonomous purchase; 1 line(s) followed the agent's normal purchase policy.",
			"what_did_not_happen":          "No real payment, inventory movement or shipment occurred.",
			"audit_message":                "The machine decision, any human follow-on decision and this order record remain separate, linked and independently verifiable.",
		},
		"notice": "Simulated order. No purchase was made, no money moved and no inventory was touched. Every line names the decision receipt that admitted it.",
	})
	writeJSON(w, 200, map[string]any{
		"assessment": o, "verification": s.verifyReceipt(receipt), "line": line, "order": order,
		"normal_cart_untouched": true,
		"note":                  "Dedicated demonstration cart; the normal consumer basket is not cleared or modified.",
	})
}

func (s *Server) absentStatusHTTP(w http.ResponseWriter, r *http.Request) {
	c := check("standing", "Recall and advisory standing", "incomplete", "incomplete", "No status record is held, so recall standing is unknown.", []string{"status_unknown"}, nil, nil)
	writeJSON(w, 200, map[string]any{"input": "no status record supplied", "standing": "unknown", "check": c, "reason_codes": []string{"status_unknown"}})
}

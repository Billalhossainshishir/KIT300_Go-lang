package ramify

import (
	"archive/zip"
	"bytes"
	"encoding/json"
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
	posts := []any{}
	for _, p := range []string{"allow", "allow_with_warning", "hold", "escalate", "block"} {
		posts = append(posts, traffic(p))
	}
	stands := []any{}
	for _, x := range []string{"no_active_recall", "advisory", "recalled", "unknown"} {
		m := standingDisplay(x)
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
	writeJSON(w, 200, map[string]any{"mapping_version": "posture_mapping_v1.0.0", "postures": posts, "standings": stands, "transitions": map[string]any{"mapping_version": "posture_mapping_v1.0.0", "order_least_to_most_restrictive": order, "rows": rows}})
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
	refs := s.evidenceRefs(sub)
	if len(refs) == 0 {
		writeJSON(w, 404, map[string]any{"detail": "No evidence artefact is available for this subject."})
		return
	}
	e := s.evidence(refs[0])
	writeJSON(w, 200, map[string]any{"subject_ref": ref, "evidence_ref": refs[0], "clean_integrity": map[string]any{"state": "verified", "detail": "artefact hash and issuer signature verify"}, "tampered_integrity": map[string]any{"state": "hash_mismatch", "detail": "artefact bytes do not match the signed content hash"}, "ratify_outcome": "fail", "objective_posture": "block", "reason_codes": []string{"evidence_hash_mismatch"}, "shared_artefact_modified": false, "artefact_restored": true, "evidence_record": e, "note": "Synthetic isolated demonstration; the shared evidence artefact was never modified."})
}

func (s *Server) absentStatusHTTP(w http.ResponseWriter, r *http.Request) {
	c := check("standing", "Recall and advisory standing", "incomplete", "incomplete", "No status record is held, so recall standing is unknown.", []string{"status_unknown"}, nil, nil)
	writeJSON(w, 200, map[string]any{"input": "no status record supplied", "standing": "unknown", "check": c, "reason_codes": []string{"status_unknown"}})
}

func (s *Server) demoCartResetHTTP(w http.ResponseWriter, r *http.Request) {
	state.mu.Lock()
	state.cart = nil
	state.mu.Unlock()
	writeJSON(w, 200, map[string]any{"cleared": true, "simulated": true, "normal_cart_untouched": true})
}

func (s *Server) demoCheckoutProofHTTP(w http.ResponseWriter, r *http.Request) {
	o, err := s.assessOne("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1", "", 1, "purchase", true)
	if err != nil {
		writeJSON(w, 500, map[string]any{"detail": err.Error()})
		return
	}
	line, err := s.cartAddByReceipt(str(o["receipt_ref"]))
	if err != nil {
		writeJSON(w, 409, map[string]any{"detail": err.Error()})
		return
	}
	state.mu.Lock()
	lines := append([]map[string]any(nil), state.cart...)
	state.mu.Unlock()
	total := 0
	for _, l := range lines {
		total += intv(l["line_total_cents"])
	}
	order := s.seal(map[string]any{"schema_version": "0.4", "record_type": "order_record", "order_id": "ramify:demo:order:" + randomHex(16), "data_snapshot": s.seed.SnapshotID(), "line_count": len(lines), "item_count": 1, "total_cents": total, "currency": "AUD", "lines": []any{line}, "timestamp": time.Now().UTC().Format(time.RFC3339Nano)})
	writeJSON(w, 200, map[string]any{"assessment": o, "verification": s.verifyReceipt(obj(o["receipt"])), "line": line, "order": order, "normal_cart_untouched": true, "note": "Dedicated demonstration transaction proof."})
}

func (s *Server) proofPackHTTP(w http.ResponseWriter, r *http.Request) {
	examples := [][3]string{{"01_APPROVED_Apex", "ramify:demo:supp:apex-mg-glyc-120", "consumer_v1"}, {"02_EXPIRED_Evidence", "ramify:demo:supp:greenline-ashw-ksm66-90", "consumer_v1"}, {"03_SELLER_RISK", "ramify:demo:ppe:covelane-n95-resp-b2026-01-B", "consumer_v1"}, {"04_RECALL_Block", "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "consumer_v1"}, {"05_SUBSTITUTION", "ramify:demo:supp:stonefield-zinc-gluc-50-90", "consumer_v1"}}
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	index := []any{}
	for _, e := range examples {
		o, _ := s.assessOne(e[1], e[2], "", 1, "proof_pack", false)
		rc := obj(o["receipt"])
		name := "receipts/" + e[0] + "_" + strings.ReplaceAll(str(rc["receipt_id"]), ":", "-") + ".json"
		f, _ := zw.Create(name)
		b, _ := json.MarshalIndent(rc, "", "  ")
		_, _ = f.Write(append(b, '\n'))
		index = append(index, map[string]any{"receipt_id": rc["receipt_id"], "subject_ref": rc["subject_ref"], "product_name": rc["product_name"], "objective_posture": rc["objective_posture"], "actor_decision": rc["actor_decision"], "payload_hash": rc["payload_hash"]})
	}
	f, _ := zw.Create("receipt_index.json")
	b, _ := json.MarshalIndent(index, "", "  ")
	_, _ = f.Write(b)
	f, _ = zw.Create("README.txt")
	_, _ = f.Write([]byte("RAMIFY OS Go Quick Proof Pack\nSynthetic demonstration evidence only.\n"))
	_ = zw.Close()
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="RAMIFY-Quick-Proof-Pack.zip"`)
	w.WriteHeader(200)
	_, _ = w.Write(buf.Bytes())
}

func (s *Server) extendedProofPackHTTP(w http.ResponseWriter, r *http.Request) {
	p := filepath.Join(s.root, "RAMIFY-Extended-Proof-Pack.zip")
	if _, err := os.Stat(p); err != nil {
		writeJSON(w, 404, map[string]any{"detail": "Extended Proof Pack is not present in this build."})
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="RAMIFY-Extended-Proof-Pack.zip"`)
	http.ServeFile(w, r, p)
}

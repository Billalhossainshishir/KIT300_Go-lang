package ramify

import (
	"net/http"
	"strings"
)

func (s *Server) agentStatus(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"local_model_available": false, "local_model_adapter": "go-deterministic", "fallback_available": true, "active_mode": "deterministic_fallback", "presentation_state": "ready", "presentation_detail": "Go deterministic catalogue matcher is active.", "presentation_timeout_seconds": 5, "interpretation_path": "deterministic fixed-catalogue matcher", "decision_path": "deterministic RAMIFY checks → policy → sealed receipt", "boundary": "AI may interpret and explain. Only the deterministic engine can decide trust."})
}

func (s *Server) interpret(w http.ResponseWriter, r *http.Request) {
	var q struct {
		RequestText, ActorRef, Mode string
		CandidateRefs               []string `json:"candidate_refs"`
	}
	var raw map[string]any
	if decodeBody(r, &raw) != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	q.RequestText = str(raw["request_text"])
	q.ActorRef = str(raw["actor_ref"])
	if q.ActorRef == "" {
		q.ActorRef = "consumer_v1"
	}
	for _, x := range arr(raw["candidate_refs"]) {
		q.CandidateRefs = append(q.CandidateRefs, str(x))
	}
	text := strings.TrimSpace(q.RequestText)
	if text == "" {
		writeJSON(w, 422, map[string]any{"detail": "Enter a product name, description, GTIN, SKU or local identifier."})
		return
	}
	id := s.identifyResult(text)
	if boolv(id["resolved"]) {
		writeJSON(w, 200, map[string]any{"identifier": id["subject_ref"], "actor_ref": q.ActorRef, "confidence": 1.0, "source": "exact_identifier", "note": "Matched an exact local identifier.", "candidates": id["candidates"], "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust.", "latency_us": 1, "latency_ms": 0.001})
		return
	}
	terms := strings.Fields(strings.ToLower(text))
	bestRef := ""
	best := 0
	for ref, v := range s.seed.Subjects() {
		rec := obj(v)
		hay := strings.ToLower(str(rec["name"]) + " " + str(rec["brand"]) + " " + str(rec["category"]))
		score := 0
		for _, t := range terms {
			if len(t) > 1 && strings.Contains(hay, t) {
				score++
			}
		}
		if score > best {
			best = score
			bestRef = ref
		}
	}
	if best == 0 {
		writeJSON(w, 200, map[string]any{"identifier": nil, "actor_ref": q.ActorRef, "confidence": 0.0, "source": "deterministic_catalogue_search", "note": "No product in the local catalogue clearly matched that request.", "candidates": []string{}, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust.", "latency_us": 1, "latency_ms": 0.001})
		return
	}
	rec := s.seed.Subject(bestRef)
	writeJSON(w, 200, map[string]any{"identifier": bestRef, "actor_ref": q.ActorRef, "confidence": 0.85, "source": "deterministic_catalogue_search", "note": "Matched " + str(rec["name"]) + " from the fixed local catalogue.", "candidates": []string{bestRef}, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust.", "latency_us": 1, "latency_ms": 0.001})
}

func (s *Server) explainHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	receipt := obj(q["receipt"])
	rep := s.verifyReceipt(receipt)
	if !boolv(rep["hash_valid"]) || !boolv(rep["signature_valid"]) {
		writeJSON(w, 422, map[string]any{"detail": "RAMIFY will only explain a receipt whose hash and signature are intact."})
		return
	}
	summary := str(receipt["product_name"]) + ". Objective posture: " + str(receipt["objective_posture"]) + ". Agent decision: " + str(receipt["actor_decision"]) + ". Permitted action: " + str(receipt["selected_action"]) + "."
	writeJSON(w, 200, map[string]any{"authoritative_summary": summary, "explanation": summary, "source": "deterministic_summary_go", "model_text_accepted": false, "presentation_only": true, "authoritative": false})
}

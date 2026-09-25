package ramify

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strings"
	"time"
)

const defaultOllamaBaseURL = "http://127.0.0.1:11434"

func localModelName() string {
	if v := strings.TrimSpace(os.Getenv("RAMIFY_LOCAL_MODEL")); v != "" {
		return v
	}
	return "llama3.1"
}

func ollamaBaseURL() string {
	if v := strings.TrimRight(strings.TrimSpace(os.Getenv("RAMIFY_OLLAMA_BASE_URL")), "/"); v != "" {
		return v
	}
	return defaultOllamaBaseURL
}

func localModelTimeout() time.Duration {
	if raw := strings.TrimSpace(os.Getenv("RAMIFY_LOCAL_MODEL_TIMEOUT")); raw != "" {
		if d, err := time.ParseDuration(raw); err == nil && d > 0 {
			return d
		}
		// Match the Python build's environment convention where a plain number is seconds.
		if seconds, err := time.ParseDuration(raw + "s"); err == nil && seconds > 0 {
			return seconds
		}
	}
	return 5 * time.Second
}

type ollamaRuntime struct {
	Reachable bool
	Available bool
	Models    []string
	Detail    string
	ErrorType any
	ElapsedMS float64
}

func probeOllama() ollamaRuntime {
	started := time.Now()
	if os.Getenv("RAMIFY_DISABLE_AGENT") == "1" {
		return ollamaRuntime{Detail: "Local AI was intentionally disabled; safe deterministic mode is active.", ElapsedMS: float64(time.Since(started).Microseconds()) / 1000}
	}
	client := &http.Client{Timeout: 700 * time.Millisecond}
	resp, err := client.Get(ollamaBaseURL() + "/api/tags")
	if err != nil {
		return ollamaRuntime{Detail: "Ollama is offline; deterministic mode is active.", ErrorType: fmt.Sprintf("%T", err), ElapsedMS: float64(time.Since(started).Microseconds()) / 1000}
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ollamaRuntime{Reachable: true, Detail: fmt.Sprintf("Ollama returned HTTP %d; deterministic mode is active.", resp.StatusCode), ElapsedMS: float64(time.Since(started).Microseconds()) / 1000}
	}
	var payload struct {
		Models []struct {
			Name  string `json:"name"`
			Model string `json:"model"`
		} `json:"models"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return ollamaRuntime{Reachable: true, Detail: "Ollama responded, but its model list could not be read.", ErrorType: fmt.Sprintf("%T", err), ElapsedMS: float64(time.Since(started).Microseconds()) / 1000}
	}
	models := make([]string, 0, len(payload.Models))
	want := strings.ToLower(localModelName())
	available := false
	for _, m := range payload.Models {
		name := m.Name
		if name == "" {
			name = m.Model
		}
		models = append(models, name)
		low := strings.ToLower(name)
		if low == want || strings.HasPrefix(low, want+":") || strings.HasPrefix(want, strings.TrimSuffix(low, ":latest")) {
			available = true
		}
	}
	detail := "Ollama is reachable, but the configured local model is not installed."
	if available {
		detail = "Local Ollama model is ready. Interpretation/explanation may use it; trust decisions remain deterministic."
	}
	return ollamaRuntime{Reachable: true, Available: available, Models: models, Detail: detail, ElapsedMS: float64(time.Since(started).Microseconds()) / 1000}
}

func (s *Server) agentStatus(w http.ResponseWriter, r *http.Request) {
	runtime := probeOllama()
	stateName := "offline"
	activeMode := "deterministic_fallback"
	if os.Getenv("RAMIFY_DISABLE_AGENT") == "1" {
		stateName = "disabled"
	} else if runtime.Reachable && !runtime.Available {
		stateName = "model_missing"
	} else if runtime.Available {
		stateName = "ready"
		activeMode = "local_llm"
	}
	writeJSON(w, 200, map[string]any{
		"local_model_available":        runtime.Available,
		"dependencies_installed":       true,
		"langgraph_installed":          false,
		"ollama_bridge_installed":      true,
		"ollama_daemon_reachable":      runtime.Reachable,
		"model_available":              runtime.Available,
		"model":                        localModelName(),
		"framework":                    "Native Go adapter",
		"provider":                     "Ollama",
		"base_url":                     ollamaBaseURL(),
		"detected_model_count":         len(runtime.Models),
		"detail":                       runtime.Detail,
		"status_check_ms":              runtime.ElapsedMS,
		"error_type":                   runtime.ErrorType,
		"decision_authority":           "deterministic_ramify_engine_only",
		"local_model_adapter":          "go+ollama:" + localModelName(),
		"fallback_available":           true,
		"active_mode":                  activeMode,
		"presentation_state":           stateName,
		"presentation_detail":          runtime.Detail,
		"presentation_timeout_seconds": localModelTimeout().Seconds(),
		"interpretation_path": func() string {
			if runtime.Available {
				return "native Go adapter → Ollama local LLM → validated catalogue identifier"
			}
			return "deterministic fixed-catalogue fallback"
		}(),
		"decision_path": "deterministic RAMIFY checks → policy → sealed receipt",
		"boundary":      "AI may interpret and explain. Only the deterministic engine can decide trust.",
	})
}

var tokenRx = regexp.MustCompile(`[a-z0-9]+`)

func normaliseQuery(text string) []string {
	stop := map[string]bool{"buy": true, "get": true, "please": true, "from": true, "the": true, "for": true, "me": true, "want": true, "check": true, "need": true, "show": true, "find": true, "in": true, "catalogue": true, "catalog": true, "product": true, "item": true, "looking": true, "give": true, "some": true, "this": true, "that": true, "my": true, "to": true, "of": true, "with": true}
	out := []string{}
	for _, token := range tokenRx.FindAllString(strings.ToLower(text), -1) {
		if len(token) > 1 && !stop[token] {
			out = append(out, token)
		}
	}
	return out
}

func (s *Server) candidateProducts(refs []string) []map[string]any {
	allowed := map[string]bool{}
	for _, ref := range refs {
		allowed[ref] = true
	}
	out := []map[string]any{}
	for ref, v := range s.seed.Subjects() {
		if len(refs) > 0 && !allowed[ref] {
			continue
		}
		rec := obj(v)
		seller := s.seller(str(rec["seller_ref"]))
		ids := obj(rec["identifiers"])
		out = append(out, map[string]any{
			"subject_ref": ref, "name": rec["name"], "brand": rec["brand"], "category": rec["category"],
			"seller_name": valueOr(seller, "name", ""), "gtin": valueOr(ids, "gtin", ""), "sku": valueOr(ids, "sku", ""),
		})
	}
	sort.Slice(out, func(i, j int) bool { return str(out[i]["name"]) < str(out[j]["name"]) })
	return out
}

func catalogueScore(query string, product map[string]any) int {
	terms := normaliseQuery(query)
	if len(terms) == 0 {
		return 0
	}
	hay := strings.ToLower(str(product["name"]) + " " + str(product["brand"]) + " " + str(product["category"]) + " " + str(product["gtin"]) + " " + str(product["sku"]) + " " + str(product["subject_ref"]) + " " + str(product["seller_name"]))
	name := strings.ToLower(str(product["name"]))
	score := 0
	for _, term := range terms {
		if strings.Contains(hay, term) {
			if strings.Contains(name, term) {
				score += 3
			} else {
				score++
			}
		}
	}
	return score
}

type ollamaGenerateResponse struct {
	Response string `json:"response"`
}

func callOllama(prompt string) (string, error) {
	if os.Getenv("RAMIFY_DISABLE_AGENT") == "1" {
		return "", fmt.Errorf("local AI disabled")
	}
	payload := map[string]any{
		"model": localModelName(), "prompt": prompt, "stream": false, "format": "json",
		"options": map[string]any{"temperature": 0},
	}
	body, _ := json.Marshal(payload)
	client := &http.Client{Timeout: localModelTimeout()}
	resp, err := client.Post(ollamaBaseURL()+"/api/generate", "application/json", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", fmt.Errorf("ollama returned HTTP %d", resp.StatusCode)
	}
	var out ollamaGenerateResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	if strings.TrimSpace(out.Response) == "" {
		return "", fmt.Errorf("ollama returned empty output")
	}
	return strings.TrimSpace(out.Response), nil
}

func (s *Server) tryOllamaInterpret(text, actor string, candidateRefs []string) map[string]any {
	products := s.candidateProducts(candidateRefs)
	if len(products) == 0 {
		return nil
	}
	catalogue, _ := json.Marshal(products)
	prompt := `You are the non-authoritative request interpreter for RAMIFY OS. Choose only from the supplied local catalogue. Do not make any safety, trust, approval, policy, or purchase decision. Return JSON only with keys identifier, confidence, note. identifier must be one supplied subject_ref or null. confidence must be 0..1. If ambiguous, return null.\nShopper request: ` + text + `\nCatalogue: ` + string(catalogue)
	raw, err := callOllama(prompt)
	if err != nil {
		return nil
	}
	var parsed map[string]any
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&parsed); err != nil {
		return nil
	}
	identifier := strings.TrimSpace(str(parsed["identifier"]))
	allowed := map[string]bool{}
	for _, p := range products {
		allowed[str(p["subject_ref"])] = true
	}
	if identifier == "" || strings.EqualFold(identifier, "null") || !allowed[identifier] {
		return nil
	}
	confidence := 0.75
	switch v := parsed["confidence"].(type) {
	case json.Number:
		if f, err := v.Float64(); err == nil {
			confidence = f
		}
	case float64:
		confidence = v
	}
	if confidence < 0 {
		confidence = 0
	}
	if confidence > 1 {
		confidence = 1
	}
	note := strings.TrimSpace(str(parsed["note"]))
	if note == "" {
		note = "Matched by the local Ollama model and validated against the fixed catalogue."
	}
	return map[string]any{
		"identifier": identifier, "actor_ref": actor, "confidence": confidence, "source": "go+ollama:" + localModelName(),
		"note": note, "candidates": []string{identifier}, "authoritative": false,
		"boundary": "The local model interprets the request. The deterministic engine decides trust.",
	}
}

func (s *Server) interpret(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	var raw map[string]any
	if decodeBody(r, &raw) != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	text := strings.TrimSpace(str(raw["request_text"]))
	actor := str(raw["actor_ref"])
	if actor == "" {
		actor = "consumer_v1"
	}
	mode := str(raw["mode"])
	if mode == "" {
		mode = "auto"
	}
	if mode != "auto" && mode != "deterministic" && mode != "local_llm" {
		writeJSON(w, 422, map[string]any{"detail": "mode must be auto, deterministic or local_llm"})
		return
	}
	if text == "" {
		writeJSON(w, 422, map[string]any{"detail": "Enter a product name, description, GTIN, SKU or local identifier."})
		return
	}
	candidateRefs := stringSlice(raw["candidate_refs"])
	finish := func(out map[string]any) {
		us := time.Since(started).Microseconds()
		if us < 1 {
			us = 1
		}
		out["latency_us"] = us
		out["latency_ms"] = float64(us) / 1000.0
		writeJSON(w, 200, out)
	}

	if len(candidateRefs) == 1 {
		products := s.candidateProducts(candidateRefs)
		if len(products) == 1 {
			p := products[0]
			finish(map[string]any{"identifier": p["subject_ref"], "actor_ref": actor, "confidence": 1.0, "source": "selected_catalogue_item", "note": "Exact product selected from the local catalogue.", "candidates": []string{str(p["subject_ref"])}, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust."})
			return
		}
	}
	id := s.identifyResult(text)
	allowed := map[string]bool{}
	for _, ref := range candidateRefs {
		allowed[ref] = true
	}
	if boolv(id["resolved"]) && (len(candidateRefs) == 0 || allowed[str(id["subject_ref"])]) {
		finish(map[string]any{"identifier": id["subject_ref"], "actor_ref": actor, "confidence": 1.0, "source": "exact_identifier", "note": "Matched an exact local identifier.", "candidates": id["candidates"], "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust."})
		return
	}

	if mode == "auto" || mode == "local_llm" {
		if reading := s.tryOllamaInterpret(text, actor, candidateRefs); reading != nil {
			finish(reading)
			return
		}
	}

	products := s.candidateProducts(candidateRefs)
	if len(candidateRefs) > 0 && len(products) == 0 {
		finish(map[string]any{"identifier": nil, "actor_ref": actor, "confidence": 0.0, "source": "deterministic_catalogue_search", "note": "The selected catalogue item is no longer available in this local dataset.", "candidates": []string{}, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust."})
		return
	}
	top := 0
	best := []map[string]any{}
	for _, product := range products {
		score := catalogueScore(text, product)
		if score > top {
			top = score
			best = []map[string]any{product}
		} else if score > 0 && score == top {
			best = append(best, product)
		}
	}
	fallbackSource := "deterministic_catalogue_search"
	fallbackPrefix := ""
	if mode == "local_llm" {
		fallbackSource = "deterministic_fallback"
		fallbackPrefix = "Local model unavailable; "
	}
	if top == 0 {
		finish(map[string]any{"identifier": nil, "actor_ref": actor, "confidence": 0.0, "source": fallbackSource, "note": fallbackPrefix + "No product in the local catalogue clearly matched that request.", "candidates": []string{}, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust."})
		return
	}
	terms := len(normaliseQuery(text))
	if terms < 1 {
		terms = 1
	}
	confidence := 0.55 + (float64(top)/float64(terms*3))*0.43
	if confidence > 0.98 {
		confidence = 0.98
	}
	if len(best) > 1 {
		refs := []string{}
		for i, p := range best {
			if i == 5 {
				break
			}
			refs = append(refs, str(p["subject_ref"]))
		}
		if confidence > 0.72 {
			confidence = 0.72
		}
		finish(map[string]any{"identifier": nil, "actor_ref": actor, "confidence": confidence, "source": fallbackSource, "note": fallbackPrefix + "Several catalogue products match equally well. Choose a product card to continue.", "candidates": refs, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust."})
		return
	}
	chosen := best[0]
	finish(map[string]any{"identifier": chosen["subject_ref"], "actor_ref": actor, "confidence": confidence, "source": fallbackSource, "note": fallbackPrefix + "Matched " + str(chosen["name"]) + " from the fixed local catalogue.", "candidates": []string{str(chosen["subject_ref"])}, "authoritative": false, "boundary": "Interpretation only. The deterministic engine decides trust."})
}

var postureSentence = map[string]string{
	"allow":              "Every check passed and there is no recall or advisory on record, so the agent may proceed.",
	"allow_with_warning": "The product passed, but with a finding attached that the buyer should see before proceeding.",
	"hold":               "There is an active advisory, so the agent stops and a person decides.",
	"escalate":           "There was not enough on file to reach a judgement, so the agent stops and a person decides.",
	"block":              "A check failed on grounds no policy can soften, so the agent must not proceed.",
}

var reasonSentence = map[string]string{
	"active_recall_on_batch": "this batch is under an active recall", "active_advisory_on_batch": "this batch is under an active advisory",
	"evidence_expired": "the supporting evidence has passed its validity date", "seller_authority_unverified_for_category": "the seller's authority to supply this category has not been established",
	"seller_authority_revoked": "the seller's supply authority has been revoked", "claim_rejected_or_revoked": "an issuer rejected or withdrew one of the product's claims",
	"issuers_state_conflicting_values": "two issuers state different values for the same claim", "mandatory_evidence_missing": "evidence this category requires is not attached",
	"required_claim_missing": "no issuer has asserted a claim this category requires", "identity_unresolved": "the identifier does not match any known product",
	"status_unknown": "no recall record is held for this product", "no_evidence_to_assess": "there is no evidence on file to assess", "superseded_product_available": "a replacement product is available",
}

func deterministicReceiptSummary(receipt map[string]any) string {
	objective := str(receipt["objective_posture"])
	decision := str(receipt["actor_decision"])
	name := str(receipt["product_name"])
	if name == "" {
		name = str(receipt["subject_ref"])
	}
	parts := []string{strings.TrimSpace(name + ". " + postureSentence[objective])}
	reasons := []string{}
	for _, code := range stringSlice(receipt["reason_codes"]) {
		if text := reasonSentence[code]; text != "" {
			reasons = append(reasons, text)
		}
	}
	if len(reasons) == 1 {
		parts = append(parts, "The finding was that "+reasons[0]+".")
	} else if len(reasons) > 1 {
		parts = append(parts, "The findings were that "+strings.Join(reasons[:len(reasons)-1], "; ")+"; and "+reasons[len(reasons)-1]+".")
	}
	if boolv(receipt["actor_narrowed"]) {
		parts = append(parts, fmt.Sprintf("For %s, policy narrows %s to %s; the product facts themselves did not change.", str(receipt["actor_label"]), strings.ReplaceAll(objective, "_", " "), strings.ReplaceAll(decision, "_", " ")))
	}
	parts = append(parts, "The selected action is "+strings.ReplaceAll(str(receipt["selected_action"]), "_", " ")+", and nothing beyond the signed permissions is authorised.")
	return strings.Join(parts, " ")
}

func explanationContradicts(text string, receipt map[string]any) bool {
	lower := strings.ToLower(strings.Join(strings.Fields(text), " "))
	decision := str(receipt["actor_decision"])
	approval := []string{"safe to buy", "safe to purchase", "approved to buy", "approved to purchase", "may proceed", "can proceed", "purchase is allowed", "buy this"}
	stop := []string{"must not proceed", "do not purchase", "cannot purchase", "blocked", "must stop"}
	if decision == "block" || decision == "hold" || decision == "escalate" {
		for _, phrase := range approval {
			if strings.Contains(lower, phrase) {
				return true
			}
		}
	}
	if decision == "allow" || decision == "allow_with_warning" {
		for _, phrase := range stop {
			if strings.Contains(lower, phrase) {
				return true
			}
		}
	}
	return false
}

func tryOllamaExplain(receipt map[string]any, authoritative string) string {
	payload, _ := json.Marshal(receipt)
	prompt := `You are a presentation-only explainer for RAMIFY OS. Explain the sealed receipt in plain English without changing, weakening, or strengthening any decision. Do not claim real-world safety/certification. Do not invent facts. Return JSON only: {"explanation":"..."}. Authoritative deterministic summary: ` + authoritative + `\nSealed receipt: ` + string(payload)
	raw, err := callOllama(prompt)
	if err != nil {
		return ""
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
		return ""
	}
	text := strings.TrimSpace(str(parsed["explanation"]))
	if text == "" || explanationContradicts(text, receipt) {
		return ""
	}
	return text
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
	authoritative := deterministicReceiptSummary(receipt)
	if text := tryOllamaExplain(receipt, authoritative); text != "" {
		writeJSON(w, 200, map[string]any{"authoritative_summary": authoritative, "explanation": text, "source": "go+ollama:" + localModelName(), "model_text_accepted": true, "presentation_only": true, "authoritative": false})
		return
	}
	writeJSON(w, 200, map[string]any{"authoritative_summary": authoritative, "explanation": authoritative, "source": "deterministic_summary", "model_text_accepted": false, "presentation_only": true, "authoritative": false})
}

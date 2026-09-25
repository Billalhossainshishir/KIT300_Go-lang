package ramify

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Server struct {
	root       string
	runtimeDir string
	version    string
	build      string
	seed       SeedData
	mux        *http.ServeMux
}

func New(root string) (*Server, error) {
	version := "go-migration-0.1.0"
	if raw, err := os.ReadFile(filepath.Join(root, "VERSION.txt")); err == nil {
		version = strings.TrimSpace(string(raw))
	}
	seed, err := LoadSeed(filepath.Join(root, "data", "demo_seed.json"))
	if err != nil {
		return nil, err
	}

	s := &Server{root: root, runtimeDir: runtimeDirectory(root), version: version, build: frontendBuildID(root), seed: seed, mux: http.NewServeMux()}
	if err := loadPortableSigner(root); err != nil {
		return nil, err
	}
	if err := s.loadRuntimeState(); err != nil {
		return nil, err
	}
	s.routes()
	return s, nil
}

func (s *Server) Handler() http.Handler { return noStore(s.mux) }

func (s *Server) routes() {
	s.mux.HandleFunc("GET /healthz", s.healthz)
	s.mux.HandleFunc("POST /api/v0/identify", s.identify)
	s.mux.HandleFunc("POST /api/v0/resolve", s.resolve)
	s.mux.HandleFunc("POST /api/v0/status", s.status)
	s.fullRoutes()

	// The original frontend uses root-level asset URLs such as /style.css and /shell.js.
	s.mux.HandleFunc("GET /", s.pageOrAsset)
}

func (s *Server) healthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok", "data_snapshot": s.seed.SnapshotID(), "version": s.version, "build": s.build,
		"runtime": "go", "configured_endpoint": "127.0.0.1:8000", "core_external_network_calls": false,
		"migration_status": "complete", "default_launcher_loopback_only": true, "documented_launch_loopback_only": true,
		"bound_to": "not introspected by the application", "binds_loopback_only": nil,
		"makes_external_network_calls": false, "makes_outbound_calls": nil,
		"note": "Final Go runtime. Current frontend and API behaviour are retained while the deterministic trust path remains local.",
	})
}

type identifyRequest struct {
	Identifier string `json:"identifier"`
}

type subjectRequest struct {
	SubjectRef string `json:"subject_ref"`
}

func (s *Server) identify(w http.ResponseWriter, r *http.Request) {
	var req identifyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	raw := strings.TrimSpace(req.Identifier)
	probe := strings.ToLower(raw)

	namespace, value := "", probe
	for prefix, field := range map[string]string{"gtin:": "gtin", "sku:": "sku", "local:": "local"} {
		if strings.HasPrefix(probe, prefix) {
			namespace = field
			value = strings.TrimSpace(strings.TrimPrefix(probe, prefix))
			break
		}
	}

	matches := make([]string, 0)
	methods := map[string]string{}
	for ref, rawSubject := range s.seed.Subjects() {
		subject, _ := rawSubject.(map[string]any)
		identifiers, _ := subject["identifiers"].(map[string]any)
		if namespace != "" {
			if strings.EqualFold(strings.TrimSpace(fmt.Sprint(identifiers[namespace])), value) {
				matches = append(matches, ref)
				methods[ref] = "exact_" + namespace
			}
			continue
		}
		if strings.EqualFold(ref, value) {
			matches = append(matches, ref)
			methods[ref] = "exact_subject_ref"
			continue
		}
		for field, candidate := range identifiers {
			if strings.EqualFold(strings.TrimSpace(fmt.Sprint(candidate)), value) {
				matches = append(matches, ref)
				methods[ref] = "exact_" + field
				break
			}
		}
	}
	sort.Strings(matches)
	matches = unique(matches)
	if len(matches) == 1 {
		ref := matches[0]
		subject := s.seed.Subject(ref)
		writeJSON(w, 200, map[string]any{"subject_ref": ref, "product_name": subject["name"], "match_method": methods[ref], "resolved": true, "candidates": []string{ref}, "next_action": "resolve"})
		return
	}
	if len(matches) > 1 {
		writeJSON(w, 200, map[string]any{"subject_ref": nil, "product_name": nil, "match_method": "ambiguous_exact_identifier", "resolved": false, "candidates": matches, "next_action": "disambiguate"})
		return
	}
	writeJSON(w, 200, map[string]any{"subject_ref": nil, "product_name": nil, "match_method": "no_exact_match", "resolved": false, "candidates": []string{}, "next_action": "indeterminate"})
}

func (s *Server) resolve(w http.ResponseWriter, r *http.Request) {
	var req subjectRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	ref := req.SubjectRef
	generatedAt := rfc3339Nano(time.Now().UTC())
	freshness := map[string]any{"generated_at": generatedAt, "ttl_seconds": freshnessTTLSeconds, "data_snapshot": s.seed.SnapshotID()}
	subject := s.seed.Subject(ref)
	if subject == nil {
		writeJSON(w, 200, map[string]any{"subject_ref": ref, "canonical_state": "observed", "identifiers": map[string]any{}, "freshness": freshness, "known": false})
		return
	}
	claims, _ := subject["claims"].([]any)
	state := "observed"
	if len(claims) > 0 {
		state = "asserted"
	}
	out := map[string]any{"subject_ref": ref, "canonical_state": state, "product_name": subject["name"], "brand": subject["brand"], "category": subject["category"], "seller_ref": subject["seller_ref"], "identifiers": subject["identifiers"], "freshness": freshness, "known": true}
	for _, key := range []string{"batch_ref", "superseded_by", "supersedes"} {
		if v, ok := subject[key]; ok {
			out[key] = v
		}
	}
	if _, ok := subject["superseded_by"]; ok {
		out["supersession_note"] = subject["supersession_note"]
	}
	writeJSON(w, 200, out)
}

func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	var req subjectRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	ref := req.SubjectRef
	record := s.seed.Status(ref)
	if record == nil {
		writeJSON(w, 200, map[string]any{"subject_ref": ref, "standing": "unknown", "scope": "product", "issuer_ref": nil, "reason": "no_status_record_held", "detail": "No status record is held for this subject.", "issued_at": nil})
		return
	}
	out := map[string]any{"subject_ref": ref, "standing": record["standing"], "scope": record["scope"], "issuer_ref": record["issuer_ref"], "reason": valueOr(record, "reason", ""), "detail": valueOr(record, "detail", ""), "issued_at": record["issued_at"]}
	if v, ok := record["batch_ref"]; ok {
		out["batch_ref"] = v
	}
	writeJSON(w, 200, out)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func noStore(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
		w.Header().Set("Pragma", "no-cache")
		w.Header().Set("Expires", "0")
		next.ServeHTTP(w, r)
	})
}

func (s *Server) fullRoutes() {
	m := s.mux
	m.HandleFunc("GET /api/v0/agent/status", s.agentStatus)
	m.HandleFunc("POST /api/v0/interpret", s.interpret)
	m.HandleFunc("POST /api/v0/verify", s.verifyPrimitive)
	m.HandleFunc("POST /api/v0/assess", s.assessHTTP)
	m.HandleFunc("POST /api/v0/compare", s.compareHTTP)
	m.HandleFunc("POST /api/v0/alternatives", s.alternativesHTTP)
	m.HandleFunc("POST /api/v0/action", s.actionHTTP)
	m.HandleFunc("GET /api/v0/actions", s.actionsHTTP)
	m.HandleFunc("GET /api/v0/actions/verify", s.actionsVerifyHTTP)
	m.HandleFunc("GET /api/v0/vocabulary", s.vocabularyHTTP)
	m.HandleFunc("GET /api/v0/cart", s.cartHTTP)
	m.HandleFunc("POST /api/v0/cart/add", s.cartAddHTTP)
	m.HandleFunc("POST /api/v0/requisition/create", s.requisitionHTTP)
	m.HandleFunc("DELETE /api/v0/cart/line/{line_id}", s.cartRemoveHTTP)
	m.HandleFunc("DELETE /api/v0/cart", s.cartClearHTTP)
	m.HandleFunc("POST /api/v0/cart/checkout", s.checkoutHTTP)
	m.HandleFunc("GET /api/v0/agents", s.agentsHTTP)
	m.HandleFunc("POST /api/v0/agents", s.agentCreateHTTP)
	m.HandleFunc("POST /api/v0/agents/preview", s.agentPreviewHTTP)
	m.HandleFunc("PUT /api/v0/agents/{ref}", s.agentSaveHTTP)
	m.HandleFunc("DELETE /api/v0/agents/{ref}", s.agentResetHTTP)
	m.HandleFunc("GET /api/v0/review/queue", s.reviewQueueHTTP)
	m.HandleFunc("POST /api/v0/receipt/verify", s.receiptVerifyHTTP)
	m.HandleFunc("POST /api/v0/receipt/review", s.receiptReviewHTTP)
	m.HandleFunc("GET /api/v0/receipts", s.receiptsHTTP)
	m.HandleFunc("GET /api/v0/receipt/{receipt_id...}", s.receiptHTTP)
	m.HandleFunc("GET /api/v0/catalogue", s.catalogueHTTP)
	m.HandleFunc("GET /api/v0/subject/{subject_ref...}", s.subjectHTTP)
	m.HandleFunc("POST /api/v0/explain", s.explainHTTP)
	m.HandleFunc("GET /api/v0/ledger/verify", s.ledgerVerifyHTTP)
	m.HandleFunc("GET /api/v0/demo/coverage", s.coverageHTTP)
	m.HandleFunc("POST /api/v0/demo/evidence-tamper", s.evidenceTamperHTTP)
	m.HandleFunc("GET /api/v0/demo/absent-status", s.absentStatusHTTP)
	m.HandleFunc("POST /api/v0/demo/cart/reset", s.demoCartResetHTTP)
	m.HandleFunc("POST /api/v0/demo/checkout-proof", s.demoCheckoutProofHTTP)
	m.HandleFunc("GET /api/v0/proof-pack", s.proofPackHTTP)
	m.HandleFunc("GET /api/v0/proof-pack/extended", s.extendedProofPackHTTP)
}

func decodeBody(r *http.Request, dst any) error {
	dec := json.NewDecoder(io.LimitReader(r.Body, 2<<20))
	dec.UseNumber()
	return dec.Decode(dst)
}

func (s *Server) verifyPrimitive(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	if decodeBody(r, &q) != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	ref := str(q["subject_ref"])
	id := s.identifyResult(ref)
	writeJSON(w, 200, s.ratify(ref, id, s.statusResult(ref)))
}

func (s *Server) assessHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	if decodeBody(r, &q) != nil {
		writeJSON(w, 422, map[string]any{"detail": "invalid JSON"})
		return
	}
	actor := str(q["actor_ref"])
	if actor == "" {
		actor = "consumer_v1"
	}
	qty := intv(q["quantity"])
	if qty == 0 {
		qty = 1
	}
	ctx := str(q["context"])
	if ctx == "" {
		ctx = "decision"
	}
	out, err := s.assessOne(str(q["identifier"]), actor, str(q["policy_ref"]), qty, ctx, true)
	if err != nil {
		writeJSON(w, 400, map[string]any{"detail": err.Error()})
		return
	}
	writeJSON(w, 200, out)
}

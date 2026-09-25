package ramify

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func repoRoot(t *testing.T) string {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve test path")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}
func newTestServer(t *testing.T) *Server {
	t.Helper()
	t.Setenv("RAMIFY_DATA_DIR", t.TempDir())
	s, err := New(repoRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func request(t *testing.T, s *Server, method, path string, body any) *httptest.ResponseRecorder {
	var r *http.Request
	if body == nil {
		r = httptest.NewRequest(method, path, nil)
	} else {
		b, _ := json.Marshal(body)
		r = httptest.NewRequest(method, path, bytes.NewReader(b))
		r.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	return w
}
func TestCurrentFrontendAndAssetsServe(t *testing.T) {
	s := newTestServer(t)
	for _, p := range []string{
		"/", "/shop", "/demo", "/david-demo", "/tour", "/cart", "/agents", "/review",
		"/activity", "/human-receipt", "/technical", "/proof-pack", "/about", "/help",
		"/style.css", "/shell.js", "/console.js", "/activity.js", "/agents.js", "/cart.js",
		"/david-demo.js", "/demo.js", "/human-receipt.js", "/review.js", "/technical.js",
		"/tour.js", "/apex-magnesium-glycinate.png",
	} {
		w := request(t, s, http.MethodGet, p, nil)
		if w.Code != 200 {
			t.Fatalf("%s status=%d", p, w.Code)
		}
	}
}

func TestCurrentFrontendUXRegressionMarkers(t *testing.T) {
	root := repoRoot(t)
	read := func(rel string) string {
		t.Helper()
		b, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(rel)))
		if err != nil {
			t.Fatalf("read %s: %v", rel, err)
		}
		return string(b)
	}

	html := read("frontend/pages/console.html")
	consoleJS := read("frontend/scripts/console.js")
	shellJS := read("frontend/scripts/shell.js")
	css := read("frontend/styles/style.css")

	for _, forbidden := range []string{
		`id="trust-timeline"`,
		"new MutationObserver(",
		"new IntersectionObserver(",
		`dot.className = "ui-ripple"`,
	} {
		if strings.Contains(html+"\n"+shellJS, forbidden) {
			t.Fatalf("frontend regression marker still present: %s", forbidden)
		}
	}

	for _, required := range []struct {
		name, source, marker string
	}{
		{"empty request validation", consoleJS, "Enter a product name or select a product first."},
		{"start fresh confirmation", consoleJS, "Start a fresh journey?"},
		{"request busy state", consoleJS, `setAttribute("aria-busy", "true")`},
		{"story keyboard focus trap", consoleJS, "drawer._focusTrap"},
		{"demo story explanation", html, "Demo stories are prepared examples"},
		{"trust passport close control", shellJS, `id="trust-passport-x"`},
		{"toast live feedback", shellJS, `aria-live`},
		{"agent policy handoff", shellJS, "Agent policy handoff"},
		{"guided readability audit", css, "Final project-wide readability/performance audit"},
		{"story drawer viewport safety", css, "max-height:calc(100dvh - 24px)"},
	} {
		if !strings.Contains(required.source, required.marker) {
			t.Fatalf("%s marker missing: %s", required.name, required.marker)
		}
	}
}

func TestSeventeenScenarioParityAndReceiptVerification(t *testing.T) {
	s := newTestServer(t)
	for _, raw := range arr(s.seedMap()["scenarios"]) {
		sc := obj(raw)
		out, err := s.assessOne(str(sc["subject_ref"]), str(sc["actor"]), "", 1, "decision", false)
		if err != nil {
			t.Fatalf("%s: %v", str(sc["id"]), err)
		}
		if str(out["objective_posture"]) != str(sc["expected_objective"]) || str(out["actor_decision"]) != str(sc["expected_decision"]) {
			t.Fatalf("%s got %s/%s want %s/%s", str(sc["id"]), str(out["objective_posture"]), str(out["actor_decision"]), str(sc["expected_objective"]), str(sc["expected_decision"]))
		}
		report := s.verifyReceipt(obj(out["receipt"]))
		if ok, _ := report["verified"].(bool); !ok {
			t.Fatalf("%s receipt failed verification: %v", str(sc["id"]), report)
		}
	}
}
func TestLatestAPICompatibility(t *testing.T) {
	s := newTestServer(t)
	cases := []struct {
		method, path string
		body         any
	}{
		{"GET", "/healthz", nil}, {"GET", "/api/v0/agent/status", nil}, {"GET", "/api/v0/catalogue", nil}, {"GET", "/api/v0/vocabulary", nil}, {"GET", "/api/v0/demo/coverage", nil}, {"GET", "/api/v0/demo/absent-status", nil},
		{"POST", "/api/v0/identify", map[string]any{"identifier": "ramify:demo:supp:apex-mg-glyc-120"}},
		{"POST", "/api/v0/resolve", map[string]any{"subject_ref": "ramify:demo:supp:apex-mg-glyc-120"}},
		{"POST", "/api/v0/status", map[string]any{"subject_ref": "ramify:demo:supp:apex-mg-glyc-120"}},
		{"POST", "/api/v0/verify", map[string]any{"subject_ref": "ramify:demo:supp:apex-mg-glyc-120"}},
		{"POST", "/api/v0/assess", map[string]any{"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "consumer_v1", "quantity": 1, "context": "guided_demo"}},
		{"POST", "/api/v0/demo/evidence-tamper", map[string]any{"subject_ref": "ramify:demo:supp:apex-mg-glyc-120"}},
		{"POST", "/api/v0/demo/cart/reset", map[string]any{}},
	}
	for _, tc := range cases {
		w := request(t, s, tc.method, tc.path, tc.body)
		if w.Code < 200 || w.Code >= 300 {
			t.Fatalf("%s %s -> %d %s", tc.method, tc.path, w.Code, w.Body.String())
		}
	}
	w := request(t, s, "GET", "/api/v0/proof-pack", nil)
	if w.Code != 200 || !strings.Contains(w.Header().Get("Content-Type"), "zip") {
		t.Fatalf("proof pack status=%d type=%s", w.Code, w.Header().Get("Content-Type"))
	}
}

func resetTestState() {
	state.mu.Lock()
	defer state.mu.Unlock()
	state.receipts = make([]map[string]any, 0)
	state.actions = make([]map[string]any, 0)
	state.cart = make([]map[string]any, 0)
	state.orders = make([]map[string]any, 0)
	state.requisitions = make([]map[string]any, 0)
	state.customAgents = map[string]map[string]any{}
}

func decodeResponse(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var out map[string]any
	dec := json.NewDecoder(bytes.NewReader(w.Body.Bytes()))
	dec.UseNumber()
	if err := dec.Decode(&out); err != nil {
		t.Fatalf("decode response: %v; body=%s", err, w.Body.String())
	}
	return out
}

func TestBasketCheckoutNeverSerialisesCollectionsAsNull(t *testing.T) {
	resetTestState()
	s := newTestServer(t)

	empty := decodeResponse(t, request(t, s, http.MethodGet, "/api/v0/cart", nil))
	for _, key := range []string{"lines", "orders", "requisitions"} {
		if empty[key] == nil {
			t.Fatalf("empty cart %s must be [] not null", key)
		}
		if len(arr(empty[key])) != 0 {
			t.Fatalf("empty cart %s should contain no rows", key)
		}
	}

	assess := request(t, s, http.MethodPost, "/api/v0/assess", map[string]any{
		"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "consumer_v1", "quantity": 1, "context": "purchase",
	})
	if assess.Code != http.StatusOK {
		t.Fatalf("assess: %d %s", assess.Code, assess.Body.String())
	}
	assessment := decodeResponse(t, assess)
	add := request(t, s, http.MethodPost, "/api/v0/cart/add", map[string]any{"receipt_ref": assessment["receipt_ref"]})
	if add.Code != http.StatusOK {
		t.Fatalf("add: %d %s", add.Code, add.Body.String())
	}
	checkout := request(t, s, http.MethodPost, "/api/v0/cart/checkout", map[string]any{})
	if checkout.Code != http.StatusOK {
		t.Fatalf("checkout: %d %s", checkout.Code, checkout.Body.String())
	}
	result := decodeResponse(t, checkout)
	cart := obj(result["cart"])
	if cart["lines"] == nil || len(arr(cart["lines"])) != 0 {
		t.Fatalf("checkout cart lines must be an empty JSON array, got %#v", cart["lines"])
	}
	order := obj(result["order"])
	if obj(order["customer_summary"]) == nil {
		t.Fatal("signed order should include customer_summary")
	}
	verify := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/receipt/verify", order))
	if !boolv(verify["verified"]) || !boolv(verify["lines_intact"]) {
		t.Fatalf("order verification failed: %#v", verify)
	}
}

func TestDemoProofsDoNotMutateNormalBasket(t *testing.T) {
	resetTestState()
	s := newTestServer(t)
	assess := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/assess", map[string]any{
		"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "consumer_v1", "quantity": 1, "context": "purchase",
	}))
	if w := request(t, s, http.MethodPost, "/api/v0/cart/add", map[string]any{"receipt_ref": assess["receipt_ref"]}); w.Code != http.StatusOK {
		t.Fatalf("cart add: %d %s", w.Code, w.Body.String())
	}
	if w := request(t, s, http.MethodPost, "/api/v0/demo/cart/reset", map[string]any{}); w.Code != http.StatusOK {
		t.Fatalf("demo reset: %d %s", w.Code, w.Body.String())
	}
	if w := request(t, s, http.MethodPost, "/api/v0/demo/checkout-proof", map[string]any{}); w.Code != http.StatusOK {
		t.Fatalf("demo checkout proof: %d %s", w.Code, w.Body.String())
	}
	cart := decodeResponse(t, request(t, s, http.MethodGet, "/api/v0/cart", nil))
	if intv(cart["line_count"]) != 1 {
		t.Fatalf("demo proof modified normal basket: %#v", cart)
	}
}

func TestEvidenceTamperDemoUsesRealBytesAndFailsClosed(t *testing.T) {
	resetTestState()
	s := newTestServer(t)
	w := request(t, s, http.MethodPost, "/api/v0/demo/evidence-tamper", map[string]any{"subject_ref": "ramify:demo:supp:apex-mg-glyc-120"})
	if w.Code != http.StatusOK {
		t.Fatalf("tamper demo: %d %s", w.Code, w.Body.String())
	}
	out := decodeResponse(t, w)
	if str(obj(out["clean_integrity"])["state"]) != "verified" || str(obj(out["tampered_integrity"])["state"]) != "hash_mismatch" {
		t.Fatalf("unexpected integrity states: %#v", out)
	}
	if str(out["objective_posture"]) != "block" || !contains(stringSlice(out["reason_codes"]), "evidence_hash_mismatch") {
		t.Fatalf("tamper demo did not fail closed: %#v", out)
	}
	if boolv(out["shared_artefact_modified"]) {
		t.Fatal("tamper demo must never modify shared evidence")
	}
}

func TestRuntimeStateSurvivesRestart(t *testing.T) {
	resetTestState()
	dir := t.TempDir()
	t.Setenv("RAMIFY_DATA_DIR", dir)
	s, err := New(repoRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	assess := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/assess", map[string]any{
		"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "consumer_v1", "quantity": 1, "context": "purchase",
	}))
	if w := request(t, s, http.MethodPost, "/api/v0/cart/add", map[string]any{"receipt_ref": assess["receipt_ref"]}); w.Code != http.StatusOK {
		t.Fatalf("cart add: %d %s", w.Code, w.Body.String())
	}
	create := request(t, s, http.MethodPost, "/api/v0/agents", map[string]any{
		"label": "Persistent test agent", "summary": "", "description": "test", "autonomy_level": "none", "purchase_style": "cart",
		"budget_limit_cents": 2500, "brand_allowlist": []string{"Apex Nutrients"}, "approved_vendors": nil, "warned_outcome_requires_review": false,
	})
	if create.Code != http.StatusOK {
		t.Fatalf("agent create: %d %s", create.Code, create.Body.String())
	}
	created := decodeResponse(t, create)

	// Constructing a new server over the same data directory simulates closing
	// and reopening the one-click application.
	s2, err := New(repoRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	cart := decodeResponse(t, request(t, s2, http.MethodGet, "/api/v0/cart", nil))
	if intv(cart["line_count"]) != 1 {
		t.Fatalf("basket did not survive restart: %#v", cart)
	}
	receipts := decodeResponse(t, request(t, s2, http.MethodGet, "/api/v0/receipts?limit=40", nil))
	if intv(receipts["total"]) < 1 {
		t.Fatalf("receipt ledger did not survive restart: %#v", receipts)
	}
	actions := decodeResponse(t, request(t, s2, http.MethodGet, "/api/v0/actions?limit=50", nil))
	if len(arr(actions["events"])) < 1 {
		t.Fatalf("action ledger did not survive restart: %#v", actions)
	}
	agents := decodeResponse(t, request(t, s2, http.MethodGet, "/api/v0/agents", nil))
	found := false
	for _, raw := range arr(agents["agents"]) {
		if str(obj(raw)["ref"]) == str(created["ref"]) {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("custom agent did not survive restart: %s", created["ref"])
	}
}

func TestNativeGoOllamaAdapterIsPresentationOnly(t *testing.T) {
	resetTestState()
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/tags":
			writeJSON(w, 200, map[string]any{"models": []any{map[string]any{"name": "llama3.1:latest"}}})
		case "/api/generate":
			body, _ := io.ReadAll(r.Body)
			if strings.Contains(string(body), "Shopper request") {
				writeJSON(w, 200, map[string]any{"response": `{"identifier":"ramify:demo:supp:apex-mg-glyc-120","confidence":0.91,"note":"Validated local catalogue match."}`})
			} else {
				writeJSON(w, 200, map[string]any{"response": `{"explanation":"This is a presentation-only explanation of the sealed demo receipt."}`})
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer fake.Close()
	t.Setenv("RAMIFY_OLLAMA_BASE_URL", fake.URL)
	t.Setenv("RAMIFY_LOCAL_MODEL", "llama3.1")
	t.Setenv("RAMIFY_DATA_DIR", t.TempDir())
	t.Setenv("RAMIFY_DISABLE_AGENT", "")
	s, err := New(repoRoot(t))
	if err != nil {
		t.Fatal(err)
	}
	status := decodeResponse(t, request(t, s, http.MethodGet, "/api/v0/agent/status", nil))
	if !boolv(status["local_model_available"]) || str(status["active_mode"]) != "local_llm" {
		t.Fatalf("local model was not detected: %#v", status)
	}
	reading := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/interpret", map[string]any{
		"request_text": "please find the magnesium option for me", "actor_ref": "consumer_v1", "mode": "auto",
	}))
	if str(reading["source"]) != "go+ollama:llama3.1" || str(reading["identifier"]) != "ramify:demo:supp:apex-mg-glyc-120" {
		t.Fatalf("unexpected local-model interpretation: %#v", reading)
	}
	assessment := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/assess", map[string]any{
		"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "consumer_v1", "quantity": 1, "context": "guided_demo",
	}))
	explanation := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/explain", map[string]any{"receipt": assessment["receipt"]}))
	if !boolv(explanation["model_text_accepted"]) || str(explanation["source"]) != "go+ollama:llama3.1" {
		t.Fatalf("unexpected local-model explanation: %#v", explanation)
	}
	// The model never replaces the signed decision object.
	if str(obj(assessment["receipt"])["objective_posture"]) != "allow" {
		t.Fatalf("local model altered trust outcome: %#v", assessment)
	}
}

func TestProofPacksContainCurrentVerificationMaterial(t *testing.T) {
	resetTestState()
	s := newTestServer(t)
	for _, tc := range []struct {
		path string
		want int
	}{{"/api/v0/proof-pack", 5}, {"/api/v0/proof-pack/extended", 6}} {
		w := request(t, s, http.MethodGet, tc.path, nil)
		if w.Code != http.StatusOK {
			t.Fatalf("%s: %d %s", tc.path, w.Code, w.Body.String())
		}
		zr, err := zip.NewReader(bytes.NewReader(w.Body.Bytes()), int64(w.Body.Len()))
		if err != nil {
			t.Fatalf("%s invalid zip: %v", tc.path, err)
		}
		names := map[string]bool{}
		receipts := 0
		for _, f := range zr.File {
			names[f.Name] = true
			if strings.HasPrefix(f.Name, "receipts/") && strings.HasSuffix(f.Name, ".json") {
				receipts++
			}
		}
		for _, required := range []string{"manifest.json", "receipt_index.json", "trust/public_keys.json", "verify_receipts.go", "policy/policy_pack_demo_v1.json", "evidence/evidence_signatures.json"} {
			if !names[required] {
				t.Fatalf("%s missing %s", tc.path, required)
			}
		}
		if receipts != tc.want {
			t.Fatalf("%s receipt count=%d want=%d", tc.path, receipts, tc.want)
		}
	}
}

func TestHumanReviewSuccessorAndRequisitionParity(t *testing.T) {
	resetTestState()
	s := newTestServer(t)
	// Active advisory -> hold -> one human successor -> authorised simulated basket line.
	hold := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/assess", map[string]any{
		"identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z", "actor_ref": "consumer_v1", "quantity": 1, "context": "purchase",
	}))
	if str(hold["actor_decision"]) != "hold" {
		t.Fatalf("expected hold, got %#v", hold)
	}
	review := request(t, s, http.MethodPost, "/api/v0/receipt/review", map[string]any{
		"receipt_id": hold["receipt_ref"], "outcome": "overridden", "reviewer_name": "Demo reviewer", "reviewer_role": "Customer / approver", "reviewer_note": "One simulated transaction.",
	})
	if review.Code != http.StatusOK {
		t.Fatalf("review: %d %s", review.Code, review.Body.String())
	}
	successor := decodeResponse(t, review)
	rc := obj(successor["receipt"])
	if obj(rc["human_receipt"]) == nil || str(rc["selected_action"]) != "human_authorised_purchase" {
		t.Fatalf("successor missing human receipt/authority: %#v", rc)
	}
	if w := request(t, s, http.MethodPost, "/api/v0/cart/add", map[string]any{"receipt_ref": successor["receipt_ref"]}); w.Code != http.StatusOK {
		t.Fatalf("human-authorised cart add: %d %s", w.Code, w.Body.String())
	}
	if w := request(t, s, http.MethodPost, "/api/v0/receipt/review", map[string]any{"receipt_id": hold["receipt_ref"], "outcome": "overridden"}); w.Code != http.StatusConflict {
		t.Fatalf("second review should conflict, got %d", w.Code)
	}
	// Clean procurement actor must stage a requisition, not silently use consumer basket semantics.
	proc := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/assess", map[string]any{
		"identifier": "ramify:demo:supp:apex-mg-glyc-120", "actor_ref": "procurement_v1", "quantity": 1, "context": "purchase",
	}))
	if str(proc["selected_action"]) != "create_mock_requisition" {
		t.Fatalf("unexpected procurement action: %#v", proc)
	}
	req := request(t, s, http.MethodPost, "/api/v0/requisition/create", map[string]any{"receipt_ref": proc["receipt_ref"]})
	if req.Code != http.StatusOK {
		t.Fatalf("requisition: %d %s", req.Code, req.Body.String())
	}
	requisition := obj(decodeResponse(t, req)["requisition"])
	if obj(requisition["customer_summary"]) == nil {
		t.Fatal("requisition should carry signed customer_summary")
	}
	verified := decodeResponse(t, request(t, s, http.MethodPost, "/api/v0/receipt/verify", requisition))
	if !boolv(verified["verified"]) || !boolv(verified["lines_intact"]) {
		t.Fatalf("requisition verification failed: %#v", verified)
	}
}

func TestAgentEditorCRUDAndDerivedPolicy(t *testing.T) {
	resetTestState()
	s := newTestServer(t)
	payload := map[string]any{
		"label": "Demo budget agent", "summary": "", "description": "Created by compatibility test", "autonomy_level": "clean_only", "purchase_style": "cart",
		"budget_limit_cents": 3000, "brand_allowlist": []string{"Apex Nutrients"}, "approved_vendors": nil, "warned_outcome_requires_review": false,
	}
	preview := request(t, s, http.MethodPost, "/api/v0/agents/preview", payload)
	if preview.Code != http.StatusOK {
		t.Fatalf("preview: %d %s", preview.Code, preview.Body.String())
	}
	pv := decodeResponse(t, preview)
	if str(pv["derived_summary"]) == "" || len(arr(pv["narrowing_rules"])) == 0 {
		t.Fatalf("preview missing derived policy: %#v", pv)
	}
	create := request(t, s, http.MethodPost, "/api/v0/agents", payload)
	if create.Code != http.StatusOK {
		t.Fatalf("create: %d %s", create.Code, create.Body.String())
	}
	created := decodeResponse(t, create)
	ref := str(created["ref"])
	payload["budget_limit_cents"] = 8000
	update := request(t, s, http.MethodPut, "/api/v0/agents/"+ref, payload)
	if update.Code != http.StatusOK || intv(decodeResponse(t, update)["budget_limit_cents"]) != 8000 {
		t.Fatalf("update failed: %d %s", update.Code, update.Body.String())
	}
	reset := request(t, s, http.MethodDelete, "/api/v0/agents/"+ref, nil)
	if reset.Code != http.StatusOK || !boolv(decodeResponse(t, reset)["deleted"]) {
		t.Fatalf("custom profile delete/reset failed: %d %s", reset.Code, reset.Body.String())
	}
}

package ramify

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
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
	for _, p := range []string{"/", "/shop", "/demo", "/david-demo", "/cart", "/agents", "/review", "/activity", "/technical", "/proof-pack", "/about", "/help", "/style.css", "/shell.js", "/console.js", "/david-demo.js", "/apex-magnesium-glycinate.png"} {
		w := request(t, s, http.MethodGet, p, nil)
		if w.Code != 200 {
			t.Fatalf("%s status=%d", p, w.Code)
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

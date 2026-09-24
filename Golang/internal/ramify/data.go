package ramify

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

const freshnessTTLSeconds = 3600

func valueOr(m map[string]any, key string, fallback any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return fallback
}

func unique(in []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(in))
	for _, v := range in {
		if !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	return out
}

func rfc3339Nano(t time.Time) string { return t.UTC().Format(time.RFC3339Nano) }

type SeedData map[string]any

func LoadSeed(path string) (SeedData, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read seed: %w", err)
	}
	var seed SeedData
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&seed); err != nil {
		return nil, fmt.Errorf("decode seed: %w", err)
	}
	return seed, nil
}

func (s SeedData) SnapshotID() string {
	meta, _ := s["meta"].(map[string]any)
	return stringValue(meta["snapshot_id"])
}

func (s SeedData) SnapshotDate() string {
	meta, _ := s["meta"].(map[string]any)
	return stringValue(meta["snapshot_date"])
}

func (s SeedData) Notice() string {
	meta, _ := s["meta"].(map[string]any)
	return stringValue(meta["notice"])
}

func (s SeedData) Subjects() map[string]any {
	v, _ := s["subjects"].(map[string]any)
	return v
}

func (s SeedData) Subject(ref string) map[string]any {
	raw, ok := s.Subjects()[ref]
	if !ok {
		return nil
	}
	v, _ := raw.(map[string]any)
	return v
}

func (s SeedData) Status(ref string) map[string]any {
	statuses, _ := s["statuses"].(map[string]any)
	raw, ok := statuses[ref]
	if !ok {
		return nil
	}
	v, _ := raw.(map[string]any)
	return v
}

func stringValue(v any) string {
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}

func str(v any) string {
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}

func obj(v any) map[string]any { x, _ := v.(map[string]any); return x }

func arr(v any) []any {
	switch x := v.(type) {
	case []any:
		return x
	case []map[string]any:
		out := make([]any, len(x))
		for i := range x {
			out[i] = x[i]
		}
		return out
	case []string:
		out := make([]any, len(x))
		for i := range x {
			out[i] = x[i]
		}
		return out
	default:
		return nil
	}
}

func intv(v any) int {
	switch x := v.(type) {
	case json.Number:
		n, _ := x.Int64()
		return int(n)
	case float64:
		return int(x)
	case int:
		return x
	case int64:
		return int(x)
	case string:
		n, _ := strconv.Atoi(x)
		return n
	}
	return 0
}

func boolv(v any) bool { b, _ := v.(bool); return b }

func copyMap(in map[string]any) map[string]any {
	b, _ := json.Marshal(in)
	var out map[string]any
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	_ = d.Decode(&out)
	return out
}

func uniqueStrings(in []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, v := range in {
		if v != "" && !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	return out
}

func contains(ss []string, q string) bool {
	for _, v := range ss {
		if v == q {
			return true
		}
	}
	return false
}

func stringSlice(v any) []string {
	out := []string{}
	for _, x := range arr(v) {
		out = append(out, str(x))
	}
	return out
}

func section(seed map[string]any, key string) map[string]any { return obj(seed[key]) }

func (s *Server) identifyResult(identifier string) map[string]any {
	raw := strings.TrimSpace(identifier)
	probe := strings.ToLower(raw)
	namespace := ""
	value := probe
	for _, p := range []struct{ pre, field string }{{"gtin:", "gtin"}, {"sku:", "sku"}, {"local:", "local"}} {
		if strings.HasPrefix(probe, p.pre) {
			namespace = p.field
			value = strings.TrimSpace(strings.TrimPrefix(probe, p.pre))
			break
		}
	}
	matches := []string{}
	methods := map[string]string{}
	for ref, rv := range s.seed.Subjects() {
		rec := obj(rv)
		ids := obj(rec["identifiers"])
		if namespace != "" {
			if strings.EqualFold(strings.TrimSpace(str(ids[namespace])), value) {
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
		for f, c := range ids {
			if strings.EqualFold(strings.TrimSpace(str(c)), value) {
				matches = append(matches, ref)
				methods[ref] = "exact_" + f
				break
			}
		}
	}
	sort.Strings(matches)
	matches = uniqueStrings(matches)
	if len(matches) == 1 {
		ref := matches[0]
		rec := s.seed.Subject(ref)
		return map[string]any{"subject_ref": ref, "product_name": rec["name"], "match_method": methods[ref], "resolved": true, "candidates": []string{ref}, "next_action": "resolve"}
	}
	if len(matches) > 1 {
		return map[string]any{"subject_ref": nil, "product_name": nil, "match_method": "ambiguous_exact_identifier", "resolved": false, "candidates": matches, "next_action": "disambiguate"}
	}
	return map[string]any{"subject_ref": nil, "product_name": nil, "match_method": "no_exact_match", "resolved": false, "candidates": []string{}, "next_action": "indeterminate"}
}

func (s *Server) statusResult(ref string) map[string]any {
	r := s.seed.Status(ref)
	if r == nil {
		return map[string]any{"subject_ref": ref, "standing": "unknown", "scope": "product", "issuer_ref": nil, "reason": "no_status_record_held", "detail": "No status record is held for this subject.", "issued_at": nil}
	}
	out := map[string]any{"subject_ref": ref, "standing": r["standing"], "scope": r["scope"], "issuer_ref": r["issuer_ref"], "reason": valueOr(r, "reason", ""), "detail": valueOr(r, "detail", ""), "issued_at": r["issued_at"]}
	if v, ok := r["batch_ref"]; ok {
		out["batch_ref"] = v
	}
	return out
}

func (s *Server) policyPack() map[string]any {
	raw, err := os.ReadFile(filepath.Join(s.root, "data", "policy_pack_demo_v1.json"))
	if err != nil {
		return map[string]any{"policy_ref": "supplements_ppe_demo_v1", "policy_version": "1.0.0", "status": "demonstration_only"}
	}
	var m map[string]any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	_ = d.Decode(&m)
	return m
}

func (s *Server) seedMap() map[string]any { return map[string]any(s.seed) }

func (s *Server) price(ref string) int {
	return intv(obj(section(s.seedMap(), "listings")["prices_cents"])[ref])
}

func (s *Server) seller(ref string) map[string]any { return obj(section(s.seedMap(), "sellers")[ref]) }

func (s *Server) issuer(ref string) map[string]any { return obj(section(s.seedMap(), "issuers")[ref]) }

func (s *Server) evidence(ref string) map[string]any {
	base := obj(section(s.seedMap(), "evidence")[ref])
	if base == nil {
		return nil
	}
	out := copyMap(base)
	raw, err := os.ReadFile(filepath.Join(s.root, "data", "evidence_signatures.json"))
	if err == nil {
		var sig map[string]any
		d := json.NewDecoder(bytes.NewReader(raw))
		d.UseNumber()
		if d.Decode(&sig) == nil {
			for k, v := range obj(sig[ref]) {
				out[k] = v
			}
		}
	}
	return out
}

func (s *Server) category(name string) map[string]any {
	return obj(section(s.seedMap(), "categories")[name])
}

func (s *Server) evidenceRefs(subject map[string]any) []string {
	refs := []string{}
	for _, cv := range arr(subject["claims"]) {
		for _, r := range stringSlice(obj(cv)["evidence_refs"]) {
			refs = append(refs, r)
		}
	}
	return uniqueStrings(refs)
}

func parseTime(v any) time.Time { t, _ := time.Parse(time.RFC3339Nano, str(v)); return t }

func (s *Server) fileDigest(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	h := sha256.Sum256(b)
	return "sha256:" + hex.EncodeToString(h[:])
}

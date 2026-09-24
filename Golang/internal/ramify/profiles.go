package ramify

import (
	"fmt"
	"net/http"
	"sort"
	"strings"
)

func (s *Server) profiles() map[string]map[string]any {
	out := map[string]map[string]any{}
	for ref, v := range section(s.seedMap(), "actor_profiles") {
		p := copyMap(obj(v))
		p["ref"] = ref
		if _, ok := p["autonomy_level"]; !ok {
			auto := stringSlice(p["auto_purchase_on"])
			level := "none"
			if len(auto) == 1 && auto[0] == "allow" {
				level = "clean_only"
			}
			if len(auto) > 1 {
				level = "clean_or_warned"
			}
			p["autonomy_level"] = level
		}
		if _, ok := p["purchase_style"]; !ok {
			style := "cart"
			if contains(stringSlice(obj(p["permitted_actions"])["allow"]), "create_mock_requisition") {
				style = "requisition"
			}
			p["purchase_style"] = style
		}
		p["built_in"] = true
		p["edited"] = false
		p["autonomy_label"] = map[string]string{"none": "Never buys without a person", "clean_only": "Buys unattended when every check passes", "clean_or_warned": "Buys unattended even when a warning is attached"}[str(p["autonomy_level"])]
		out[ref] = p
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	for ref, p := range state.customAgents {
		out[ref] = copyMap(p)
	}
	return out
}

func (s *Server) applyActor(posture, actorRef string, subject map[string]any, order map[string]any) (map[string]any, error) {
	p := s.profiles()[actorRef]
	if p == nil {
		return nil, fmt.Errorf("unknown actor profile: %s", actorRef)
	}
	decision := posture
	applied := []map[string]any{}
	codes := []string{}
	conditions := []map[string]any{}
	for _, rv := range arr(p["narrowing_rules"]) {
		r := obj(rv)
		id := str(r["id"])
		applies := false
		met := true
		detail := ""
		switch id {
		case "warned_outcome_requires_review":
			applies = posture == "allow_with_warning"
			met = !applies
			detail = "Warned outcomes need a person"
		case "seller_not_on_approved_vendor_list":
			approved := stringSlice(p["approved_vendors"])
			applies = len(approved) > 0 && !contains(approved, str(subject["seller_ref"]))
			met = !applies
			detail = "Approved vendor list"
		case "over_budget":
			limit := intv(p["budget_limit_cents"])
			total := intv(order["line_total_cents"])
			applies = limit > 0 && total > limit
			met = !applies
			detail = "Spend ceiling"
		case "brand_not_on_allowlist":
			allow := stringSlice(p["brand_allowlist"])
			applies = len(allow) > 0 && !contains(allow, str(subject["brand"]))
			met = !applies
			detail = "Brand arrangement"
		}
		if id != "" {
			conditions = append(conditions, map[string]any{"id": id, "kind": ruleKind(id), "label": detail, "detail": detail, "met": met})
		}
		if applies {
			candidate := str(r["narrow_to"])
			if restrict[candidate] > restrict[decision] {
				decision = candidate
				code := str(r["reason_code"])
				applied = append(applied, map[string]any{"rule_id": id, "kind": ruleKind(id), "narrowed_to": candidate, "reason_code": code})
				codes = append(codes, code)
			}
		}
	}
	return map[string]any{"actor_ref": actorRef, "actor_label": p["label"], "objective_posture": posture, "decision": decision, "narrowed": decision != posture, "applied_rules": applied, "conditions_evaluated": conditions, "reason_codes": uniqueStrings(codes), "profile": p}, nil
}

func ruleKind(id string) string {
	if id == "warned_outcome_requires_review" {
		return "trust_derived"
	}
	return "commercial"
}

func (s *Server) agentsHTTP(w http.ResponseWriter, r *http.Request) {
	agents := []any{}
	for _, p := range s.profiles() {
		agents = append(agents, p)
	}
	sort.Slice(agents, func(i, j int) bool { return str(obj(agents[i])["label"]) < str(obj(agents[j])["label"]) })
	brands := []string{}
	for _, v := range s.seed.Subjects() {
		brands = append(brands, str(obj(v)["brand"]))
	}
	brands = uniqueStrings(brands)
	sort.Strings(brands)
	sellers := []any{}
	for ref, v := range section(s.seedMap(), "sellers") {
		sellers = append(sellers, map[string]any{"ref": ref, "name": obj(v)["name"]})
	}
	writeJSON(w, 200, map[string]any{"agents": agents, "autonomy_levels": []any{map[string]any{"value": "none", "label": "Never buys without a person"}, map[string]any{"value": "clean_only", "label": "Buys unattended when every check passes"}, map[string]any{"value": "clean_or_warned", "label": "Buys unattended even when a warning is attached"}}, "brands": brands, "sellers": sellers})
}

func compileAgent(fields map[string]any, ref string) map[string]any {
	p := copyMap(fields)
	p["ref"] = ref
	if str(p["label"]) == "" {
		p["label"] = "Custom agent"
	}
	level := str(p["autonomy_level"])
	if level == "" {
		level = "none"
	}
	style := str(p["purchase_style"])
	if style == "" {
		style = "cart"
	}
	if style == "requisition" {
		level = "none"
	}
	p["autonomy_level"] = level
	p["purchase_style"] = style
	auto := []string{}
	if level == "clean_only" {
		auto = []string{"allow"}
	} else if level == "clean_or_warned" {
		auto = []string{"allow", "allow_with_warning"}
	}
	p["auto_purchase_on"] = auto
	p["autonomy"] = "assists"
	if len(auto) > 0 && style == "cart" {
		p["autonomy"] = "purchases_unattended"
	}
	primary := "add_to_mock_cart"
	if style == "requisition" {
		primary = "create_mock_requisition"
	}
	buy := func(d string) []string {
		a := []string{}
		if contains(auto, d) {
			a = append(a, "purchase_autonomously")
		}
		a = append(a, primary, "compare_alternatives")
		return a
	}
	p["permitted_actions"] = map[string]any{"allow": buy("allow"), "allow_with_warning": buy("allow_with_warning"), "hold": []string{"create_review_task", "compare_alternatives", "halt"}, "escalate": []string{"create_review_task", "halt"}, "block": []string{"halt"}}
	rules := []any{}
	if boolv(p["warned_outcome_requires_review"]) || (len(auto) == 1 && auto[0] == "allow") {
		code := "warned_outcome_requires_a_person"
		if len(auto) > 0 {
			code = "autonomy_withheld_on_warned_outcome"
		}
		rules = append(rules, map[string]any{"id": "warned_outcome_requires_review", "narrow_to": "hold", "reason_code": code})
	}
	if intv(p["budget_limit_cents"]) > 0 {
		rules = append(rules, map[string]any{"id": "over_budget", "narrow_to": "hold", "reason_code": "line_total_exceeds_agent_budget"})
	}
	if len(stringSlice(p["brand_allowlist"])) > 0 {
		rules = append(rules, map[string]any{"id": "brand_not_on_allowlist", "narrow_to": "hold", "reason_code": "brand_outside_agent_arrangement"})
	}
	if len(stringSlice(p["approved_vendors"])) > 0 {
		rules = append(rules, map[string]any{"id": "seller_not_on_approved_vendor_list", "narrow_to": "hold", "reason_code": "seller_not_on_approved_vendor_list"})
	}
	p["narrowing_rules"] = rules
	p["built_in"] = false
	p["edited"] = true
	p["autonomy_label"] = map[string]string{"none": "Never buys without a person", "clean_only": "Buys unattended when every check passes", "clean_or_warned": "Buys unattended even when a warning is attached"}[level]
	return p
}

func (s *Server) agentPreviewHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	writeJSON(w, 200, compileAgent(q, "preview"))
}

func (s *Server) agentCreateHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	slug := strings.ToLower(str(q["label"]))
	slug = strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			return r
		}
		return '_'
	}, slug)
	slug = strings.Trim(slug, "_")
	ref := "custom_" + slug
	if ref == "custom_" {
		ref = "custom_agent"
	}
	p := compileAgent(q, ref)
	state.mu.Lock()
	state.customAgents[ref] = p
	state.mu.Unlock()
	writeJSON(w, 200, p)
}

func (s *Server) agentSaveHTTP(w http.ResponseWriter, r *http.Request) {
	ref := r.PathValue("ref")
	var q map[string]any
	_ = decodeBody(r, &q)
	if s.profiles()[ref] == nil {
		writeJSON(w, 404, map[string]any{"detail": "no such agent profile"})
		return
	}
	p := compileAgent(q, ref)
	state.mu.Lock()
	state.customAgents[ref] = p
	state.mu.Unlock()
	writeJSON(w, 200, p)
}

func (s *Server) agentResetHTTP(w http.ResponseWriter, r *http.Request) {
	ref := r.PathValue("ref")
	state.mu.Lock()
	delete(state.customAgents, ref)
	state.mu.Unlock()
	rest := s.profiles()[ref]
	writeJSON(w, 200, map[string]any{"restored": rest, "deleted": rest == nil})
}

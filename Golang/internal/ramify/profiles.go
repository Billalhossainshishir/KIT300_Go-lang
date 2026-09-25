package ramify

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strings"
)

var autonomyLevels = map[string][]string{
	"none":            {},
	"clean_only":      {"allow"},
	"clean_or_warned": {"allow", "allow_with_warning"},
}

var autonomyLabels = map[string]string{
	"none":            "Never buys without a person",
	"clean_only":      "Buys unattended when every check passes",
	"clean_or_warned": "Buys unattended even when a warning is attached",
}

func moneyCents(cents int) string {
	if cents%100 == 0 {
		return fmt.Sprintf("A$%d", cents/100)
	}
	return fmt.Sprintf("A$%.2f", float64(cents)/100.0)
}

func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func (s *Server) seedProfileInputs() map[string]map[string]any {
	out := map[string]map[string]any{}
	for ref, v := range section(s.seedMap(), "actor_profiles") {
		record := obj(v)
		auto := stringSlice(record["auto_purchase_on"])
		level := "none"
		for name, value := range autonomyLevels {
			if sameStrings(auto, value) {
				level = name
				break
			}
		}
		style := "cart"
		if contains(stringSlice(obj(record["permitted_actions"])["allow"]), "create_mock_requisition") {
			style = "requisition"
		}
		warned := false
		for _, rv := range arr(record["narrowing_rules"]) {
			if str(obj(rv)["id"]) == "warned_outcome_requires_review" {
				warned = true
				break
			}
		}
		out[ref] = map[string]any{
			"ref": ref, "label": record["label"], "summary": valueOr(record, "summary", ""), "description": valueOr(record, "description", ""),
			"autonomy_level": level, "purchase_style": style, "budget_limit_cents": valueOr(record, "budget_limit_cents", nil),
			"brand_allowlist": valueOr(record, "brand_allowlist", nil), "approved_vendors": valueOr(record, "approved_vendors", nil),
			"warned_outcome_requires_review": warned, "built_in": true, "edited": false,
		}
	}
	return out
}

func profileSummary(p map[string]any) string {
	parts := []string{}
	style := str(p["purchase_style"])
	level := str(p["autonomy_level"])
	if style == "requisition" {
		parts = append(parts, "stages procurement requisitions")
	} else if level == "clean_or_warned" {
		parts = append(parts, "buys unattended, warnings and all")
	} else if level == "clean_only" {
		parts = append(parts, "buys unattended on a clean result")
	} else {
		parts = append(parts, "always asks first")
	}
	if p["budget_limit_cents"] != nil {
		parts = append(parts, "up to "+moneyCents(intv(p["budget_limit_cents"]))+" a line")
	}
	if n := len(stringSlice(p["brand_allowlist"])); n > 0 {
		word := "brand"
		if n != 1 {
			word = "brands"
		}
		parts = append(parts, fmt.Sprintf("%d %s only", n, word))
	}
	if n := len(stringSlice(p["approved_vendors"])); n > 0 {
		word := "approved seller"
		if n != 1 {
			word = "approved sellers"
		}
		parts = append(parts, fmt.Sprintf("%d %s", n, word))
	}
	text := strings.Join(parts, ", ")
	if text == "" {
		return ""
	}
	return strings.ToUpper(text[:1]) + text[1:]
}

func compileAgent(fields map[string]any, ref string, builtIn, edited bool) map[string]any {
	p := copyMap(fields)
	p["ref"] = ref
	if strings.TrimSpace(str(p["label"])) == "" {
		p["label"] = "Custom agent"
	}
	if _, ok := p["summary"]; !ok {
		p["summary"] = ""
	}
	if _, ok := p["description"]; !ok {
		p["description"] = ""
	}
	level := str(p["autonomy_level"])
	if _, ok := autonomyLevels[level]; !ok {
		level = "none"
	}
	style := str(p["purchase_style"])
	if style != "requisition" {
		style = "cart"
	}
	if style == "requisition" {
		level = "none"
	}
	p["autonomy_level"] = level
	p["purchase_style"] = style
	for _, key := range []string{"budget_limit_cents", "brand_allowlist", "approved_vendors"} {
		if _, ok := p[key]; !ok {
			p[key] = nil
		}
	}
	if _, ok := p["warned_outcome_requires_review"]; !ok {
		p["warned_outcome_requires_review"] = false
	}

	auto := append([]string{}, autonomyLevels[level]...)
	if style != "cart" {
		auto = []string{}
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
	p["permitted_actions"] = map[string]any{
		"allow": buy("allow"), "allow_with_warning": buy("allow_with_warning"),
		"hold":     []string{"create_review_task", "compare_alternatives", "halt"},
		"escalate": []string{"create_review_task", "halt"}, "block": []string{"halt"},
	}

	rules := []any{}
	if boolv(p["warned_outcome_requires_review"]) {
		code := "warned_outcome_requires_a_person"
		if len(auto) > 0 {
			code = "autonomy_withheld_on_warned_outcome"
		}
		rules = append(rules, map[string]any{"id": "warned_outcome_requires_review", "when": "objective_posture == allow_with_warning", "narrow_to": "hold", "reason_code": code})
	}
	if p["budget_limit_cents"] != nil {
		rules = append(rules,
			map[string]any{"id": "price_unavailable_for_budget", "when": "line total is unavailable", "narrow_to": "hold", "reason_code": "line_total_unavailable_for_agent_budget"},
			map[string]any{"id": "over_budget", "when": "line total > budget_limit_cents", "narrow_to": "hold", "reason_code": "line_total_exceeds_agent_budget"},
		)
	}
	if len(stringSlice(p["brand_allowlist"])) > 0 {
		rules = append(rules, map[string]any{"id": "brand_not_on_allowlist", "when": "brand not in brand_allowlist", "narrow_to": "hold", "reason_code": "brand_outside_agent_arrangement"})
	}
	if len(stringSlice(p["approved_vendors"])) > 0 {
		rules = append(rules, map[string]any{"id": "seller_not_on_approved_vendor_list", "when": "seller not in approved_vendors", "narrow_to": "hold", "reason_code": "seller_not_on_approved_vendor_list"})
	}
	if len(auto) == 1 && auto[0] == "allow" && !boolv(p["warned_outcome_requires_review"]) {
		rules = append(rules, map[string]any{"id": "warned_outcome_requires_review", "when": "objective_posture == allow_with_warning", "narrow_to": "hold", "reason_code": "autonomy_withheld_on_warned_outcome"})
	}
	p["narrowing_rules"] = rules
	p["built_in"] = builtIn
	p["edited"] = edited
	p["derived_summary"] = profileSummary(p)
	if strings.TrimSpace(str(p["summary"])) == "" {
		p["summary"] = p["derived_summary"]
	}
	p["autonomy_label"] = autonomyLabels[level]
	return p
}

func (s *Server) profiles() map[string]map[string]any {
	inputs := s.seedProfileInputs()
	out := map[string]map[string]any{}
	for ref, p := range inputs {
		out[ref] = compileAgent(p, ref, true, false)
	}
	state.mu.Lock()
	custom := map[string]map[string]any{}
	for ref, p := range state.customAgents {
		custom[ref] = copyMap(p)
	}
	state.mu.Unlock()
	for ref, p := range custom {
		built := inputs[ref] != nil
		out[ref] = compileAgent(p, ref, built, true)
	}
	return out
}

func ruleKind(id string) string {
	if id == "warned_outcome_requires_review" {
		return "trust_derived"
	}
	return "commercial"
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

	if p["budget_limit_cents"] != nil {
		limit := intv(p["budget_limit_cents"])
		if order["line_total_cents"] == nil {
			conditions = append(conditions, map[string]any{"id": "price_unavailable_for_budget", "kind": "commercial", "label": "Spend ceiling " + moneyCents(limit) + " per line", "detail": "This listing carries no price, so the spend ceiling requires review.", "met": false})
		} else {
			total := intv(order["line_total_cents"])
			within := total <= limit
			detail := fmt.Sprintf("Line total %s is within the ceiling.", moneyCents(total))
			if !within {
				detail = fmt.Sprintf("Line total %s is over the ceiling.", moneyCents(total))
			}
			conditions = append(conditions, map[string]any{"id": "over_budget", "kind": "commercial", "label": "Spend ceiling " + moneyCents(limit) + " per line", "detail": detail, "met": within})
		}
	}
	if allow := stringSlice(p["brand_allowlist"]); len(allow) > 0 {
		brand := str(subject["brand"])
		permitted := contains(allow, brand)
		detail := brand + " is covered by the arrangement."
		if !permitted {
			detail = brand + " is outside the arrangement. This is a commercial restriction, not a finding about the product."
		}
		conditions = append(conditions, map[string]any{"id": "brand_not_on_allowlist", "kind": "commercial", "label": "Brand arrangement", "detail": detail, "met": permitted})
	}
	if approved := stringSlice(p["approved_vendors"]); len(approved) > 0 {
		sellerRef := str(subject["seller_ref"])
		ok := contains(approved, sellerRef)
		name := "the seller"
		if seller := s.seller(sellerRef); seller != nil {
			name = str(seller["name"])
		}
		detail := name + " is on the approved vendor list."
		if !ok {
			detail = name + " is not on the approved vendor list. The seller is genuine; the arrangement to buy from them is what is missing."
		}
		conditions = append(conditions, map[string]any{"id": "seller_not_on_approved_vendor_list", "kind": "commercial", "label": "Approved vendor list", "detail": detail, "met": ok})
	}
	for _, rv := range arr(p["narrowing_rules"]) {
		r := obj(rv)
		if str(r["id"]) == "warned_outcome_requires_review" {
			warned := posture == "allow_with_warning"
			detail := "The assessment carried no warning."
			if warned {
				detail = "The assessment carried a warning, so this cannot proceed unattended."
			}
			conditions = append(conditions, map[string]any{"id": "warned_outcome_requires_review", "kind": "trust_derived", "label": "Warned outcomes need a person", "detail": detail, "met": !warned})
			break
		}
	}

	for _, rv := range arr(p["narrowing_rules"]) {
		r := obj(rv)
		id := str(r["id"])
		applies := false
		switch id {
		case "warned_outcome_requires_review":
			applies = posture == "allow_with_warning"
		case "seller_not_on_approved_vendor_list":
			approved := stringSlice(p["approved_vendors"])
			applies = len(approved) > 0 && !contains(approved, str(subject["seller_ref"]))
		case "price_unavailable_for_budget":
			applies = p["budget_limit_cents"] != nil && order["line_total_cents"] == nil
		case "over_budget":
			applies = p["budget_limit_cents"] != nil && order["line_total_cents"] != nil && intv(order["line_total_cents"]) > intv(p["budget_limit_cents"])
		case "brand_not_on_allowlist":
			allow := stringSlice(p["brand_allowlist"])
			applies = len(allow) > 0 && !contains(allow, str(subject["brand"]))
		}
		if !applies {
			continue
		}
		candidate := str(r["narrow_to"])
		if restrict[candidate] > restrict[decision] {
			decision = candidate
			code := str(r["reason_code"])
			applied = append(applied, map[string]any{"rule_id": id, "kind": ruleKind(id), "narrowed_to": candidate, "reason_code": code})
			codes = append(codes, code)
		}
	}
	return map[string]any{"actor_ref": actorRef, "actor_label": p["label"], "objective_posture": posture, "decision": decision, "narrowed": decision != posture, "applied_rules": applied, "conditions_evaluated": conditions, "reason_codes": uniqueStrings(codes), "profile": p}, nil
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
	sort.Slice(sellers, func(i, j int) bool { return str(obj(sellers[i])["name"]) < str(obj(sellers[j])["name"]) })
	levels := []any{}
	for _, name := range []string{"none", "clean_only", "clean_or_warned"} {
		levels = append(levels, map[string]any{"value": name, "label": autonomyLabels[name]})
	}
	writeJSON(w, 200, map[string]any{"agents": agents, "autonomy_levels": levels, "brands": brands, "sellers": sellers})
}

func (s *Server) validateAgentFields(q map[string]any) error {
	label := strings.TrimSpace(str(q["label"]))
	if label == "" {
		return fmt.Errorf("An agent needs a name.")
	}
	if len(label) > 60 {
		return fmt.Errorf("Keep the name under 60 characters.")
	}
	if len(str(valueOr(q, "summary", ""))) > 120 {
		return fmt.Errorf("Keep the summary under 120 characters.")
	}
	if len(str(valueOr(q, "description", ""))) > 600 {
		return fmt.Errorf("Keep the description under 600 characters.")
	}
	level := str(valueOr(q, "autonomy_level", "none"))
	if _, ok := autonomyLevels[level]; !ok {
		return fmt.Errorf("Unknown autonomy setting: %s", level)
	}
	style := str(valueOr(q, "purchase_style", "cart"))
	if style != "cart" && style != "requisition" {
		return fmt.Errorf("Unknown purchase style: %s", style)
	}
	if q["budget_limit_cents"] != nil {
		var budget int64
		switch v := q["budget_limit_cents"].(type) {
		case json.Number:
			parsed, err := v.Int64()
			if err != nil {
				return fmt.Errorf("The spend ceiling must be a whole number of cents, not a coerced value.")
			}
			budget = parsed
		case int:
			budget = int64(v)
		case int64:
			budget = v
		default:
			return fmt.Errorf("The spend ceiling must be a whole number of cents, not a coerced value.")
		}
		if budget < 0 || budget > 100000000 {
			return fmt.Errorf("A spend ceiling must be between 0 and 100000000 cents.")
		}
	}
	validateList := func(key string, known map[string]bool, unknownPrefix string) error {
		value, exists := q[key]
		if !exists || value == nil {
			return nil
		}
		raw, ok := value.([]any)
		if !ok {
			// Tests/internal callers may use []string directly.
			if ss, ok := value.([]string); ok {
				raw = make([]any, len(ss))
				for i := range ss {
					raw[i] = ss[i]
				}
			} else {
				return fmt.Errorf("The %s must be a list.", strings.ReplaceAll(key, "_", " "))
			}
		}
		if len(raw) > 50 {
			return fmt.Errorf("The %s may contain at most 50 entries.", strings.ReplaceAll(key, "_", " "))
		}
		unknown := []string{}
		for _, item := range raw {
			text, ok := item.(string)
			if !ok || !known[text] {
				unknown = append(unknown, str(item))
			}
		}
		if len(unknown) > 0 {
			return fmt.Errorf("%s: %s", unknownPrefix, strings.Join(unknown, ", "))
		}
		return nil
	}
	brands := map[string]bool{}
	for _, record := range s.seed.Subjects() {
		brands[str(obj(record)["brand"])] = true
	}
	if err := validateList("brand_allowlist", brands, "Not a brand in this catalogue"); err != nil {
		return err
	}
	vendors := map[string]bool{}
	for ref := range section(s.seedMap(), "sellers") {
		vendors[ref] = true
	}
	if err := validateList("approved_vendors", vendors, "Not a seller in this catalogue"); err != nil {
		return err
	}
	if v, ok := q["warned_outcome_requires_review"]; ok {
		if _, ok := v.(bool); !ok {
			return fmt.Errorf("warned_outcome_requires_review must be true or false.")
		}
	}
	return nil
}

func (s *Server) agentPreviewHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	if err := s.validateAgentFields(q); err != nil {
		writeJSON(w, 400, map[string]any{"detail": err.Error()})
		return
	}
	writeJSON(w, 200, compileAgent(q, "preview", false, true))
}

func agentSlug(label string) string {
	slug := strings.ToLower(label)
	slug = strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' {
			return r
		}
		return '_'
	}, slug)
	return strings.Trim(slug, "_")
}

func (s *Server) agentCreateHTTP(w http.ResponseWriter, r *http.Request) {
	var q map[string]any
	_ = decodeBody(r, &q)
	if err := s.validateAgentFields(q); err != nil {
		writeJSON(w, 400, map[string]any{"detail": err.Error()})
		return
	}
	slug := agentSlug(str(q["label"]))
	if slug == "" {
		writeJSON(w, 400, map[string]any{"detail": "That name has no letters or numbers in it."})
		return
	}
	ref := "custom_" + slug
	existing := s.profiles()
	for suffix := 2; existing[ref] != nil; suffix++ {
		ref = fmt.Sprintf("custom_%s_%d", slug, suffix)
	}
	p := compileAgent(q, ref, false, true)
	state.mu.Lock()
	state.customAgents[ref] = p
	state.mu.Unlock()
	_ = s.persistAgents()
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
	if err := s.validateAgentFields(q); err != nil {
		writeJSON(w, 400, map[string]any{"detail": err.Error()})
		return
	}
	p := compileAgent(q, ref, s.seedProfileInputs()[ref] != nil, true)
	state.mu.Lock()
	state.customAgents[ref] = p
	state.mu.Unlock()
	_ = s.persistAgents()
	writeJSON(w, 200, p)
}

func (s *Server) agentResetHTTP(w http.ResponseWriter, r *http.Request) {
	ref := r.PathValue("ref")
	if s.profiles()[ref] == nil {
		writeJSON(w, 404, map[string]any{"detail": "no such agent profile"})
		return
	}
	state.mu.Lock()
	delete(state.customAgents, ref)
	state.mu.Unlock()
	_ = s.persistAgents()
	rest := s.profiles()[ref]
	writeJSON(w, 200, map[string]any{"restored": rest, "deleted": rest == nil})
}

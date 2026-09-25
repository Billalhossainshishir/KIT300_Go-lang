package ramify

import (
	"fmt"
	"path/filepath"
	"strings"
)

func check(id, label, outcome, severity, detail string, codes []string, evidence []string, findings []any) map[string]any {
	if codes == nil {
		codes = []string{}
	}
	if evidence == nil {
		evidence = []string{}
	}
	if findings == nil {
		findings = []any{}
	}
	return map[string]any{"check_id": id, "label": label, "outcome": outcome, "severity": severity, "detail": detail, "reason_codes": codes, "evidence_consulted": evidence, "findings": findings}
}

func (s *Server) ratify(subjectRef string, idr, status map[string]any) map[string]any {
	subject := s.seed.Subject(subjectRef)
	checks := []map[string]any{}
	if !boolv(idr["resolved"]) {
		checks = append(checks, check("identity", "Identity resolution", "incomplete", "incomplete", "Identifier does not resolve to any known subject.", []string{"identity_unresolved"}, nil, nil))
		for _, p := range [][2]string{{"standing", "Recall and advisory standing"}, {"seller_authority", "Seller authority"}, {"mandatory_evidence", "Mandatory evidence present"}, {"evidence_freshness", "Evidence validity and integrity"}, {"claims_and_category", "Claims and category requirements"}, {"conflicting_information", "Conflicting information"}} {
			checks = append(checks, check(p[0], p[1], "incomplete", "incomplete", "Not run: no subject was resolved to check against.", []string{"not_run_identity_unresolved"}, nil, nil))
		}
		return s.verifyResult(subjectRef, checks, nil)
	}
	checks = append(checks, check("identity", "Identity resolution", "pass", "informational", "Identifier resolves to exactly one subject using "+str(idr["match_method"])+".", nil, nil, nil))
	standing := str(status["standing"])
	switch standing {
	case "recalled":
		checks = append(checks, check("standing", "Recall and advisory standing", "fail", "hard_stop", str(status["detail"]), []string{"active_recall_on_batch"}, nil, nil))
	case "advisory":
		checks = append(checks, check("standing", "Recall and advisory standing", "review", "hard_stop", str(status["detail"]), []string{"active_advisory_on_batch"}, nil, nil))
	case "no_active_recall":
		checks = append(checks, check("standing", "Recall and advisory standing", "pass", "informational", "No recall or advisory is recorded against this subject.", nil, nil, nil))
	default:
		checks = append(checks, check("standing", "Recall and advisory standing", "incomplete", "incomplete", "No status record is held, so recall standing is unknown.", []string{"status_unknown"}, nil, nil))
	}
	seller := s.seller(str(subject["seller_ref"]))
	cat := str(subject["category"])
	if seller == nil {
		checks = append(checks, check("seller_authority", "Seller authority", "incomplete", "incomplete", "No seller record is held for this listing.", []string{"seller_unknown"}, nil, nil))
	} else if str(seller["authority"]) == "revoked" {
		checks = append(checks, check("seller_authority", "Seller authority", "fail", "hard_stop", str(seller["name"])+" has had its supply authority revoked.", []string{"seller_authority_revoked"}, nil, nil))
	} else if str(seller["authority"]) != "verified" || !contains(stringSlice(seller["authorised_categories"]), cat) {
		checks = append(checks, check("seller_authority", "Seller authority", "review", "policy_dependent", str(seller["name"])+" has no established authority to supply "+strings.ReplaceAll(cat, "_", " ")+".", []string{"seller_authority_unverified_for_category"}, nil, nil))
	} else {
		checks = append(checks, check("seller_authority", "Seller authority", "pass", "informational", str(seller["name"])+" is verified to supply "+strings.ReplaceAll(cat, "_", " ")+".", nil, nil, nil))
	}
	refs := s.evidenceRefs(subject)
	present := map[string]bool{}
	for _, r := range refs {
		if ev := s.evidence(r); ev != nil {
			present[str(ev["type"])] = true
		}
	}
	missing := []string{}
	for _, req := range stringSlice(s.category(cat)["required_evidence_types"]) {
		if !present[req] {
			missing = append(missing, req)
		}
	}
	if len(missing) > 0 {
		checks = append(checks, check("mandatory_evidence", "Mandatory evidence present", "incomplete", "incomplete", "Missing required evidence: "+strings.Join(missing, ", ")+".", []string{"mandatory_evidence_missing"}, refs, nil))
	} else {
		checks = append(checks, check("mandatory_evidence", "Mandatory evidence present", "pass", "informational", fmt.Sprintf("All %d required evidence type(s) are attached.", len(stringSlice(s.category(cat)["required_evidence_types"]))), nil, refs, nil))
	}
	// Evidence freshness/integrity. The Go release verifies the same artefact bytes,
	// SHA-256 digest, issuer Ed25519 signature and signed metadata/claim binding as
	// the recent FastAPI build before freshness is considered.
	snapshot := parseTime(obj(s.seedMap()["meta"])["snapshot_date"])
	worst := 0
	reasons := []string{}
	desc := []string{}
	findings := []any{}
	claimsForBinding := arr(subject["claims"])
	for _, r := range refs {
		ev := s.evidence(r)
		if ev == nil {
			continue
		}
		integ := s.evaluateEvidenceIntegrity(ev, str(subject["ref"]), claimsForBinding)
		freshness := map[string]any{"state": "current", "detail": "current"}
		local := 0
		integrityState := str(integ["state"])
		switch integrityState {
		case "verified":
		case "missing_metadata", "artefact_missing", "unknown_issuer_key":
			local = 2
			if code := integrityReason[integrityState]; code != "" {
				reasons = append(reasons, code)
			}
			desc = append(desc, r+" integrity: "+str(integ["detail"]))
		default:
			local = 3
			if code := integrityReason[integrityState]; code != "" {
				reasons = append(reasons, code)
			}
			desc = append(desc, r+" integrity: "+str(integ["detail"]))
		}
		if str(ev["record_status"]) == "revoked" || str(ev["record_status"]) == "withdrawn" {
			freshness = map[string]any{"state": "revoked", "detail": "the issuer " + str(ev["record_status"]) + " this certificate"}
			if local < 3 {
				local = 3
			}
			reasons = append(reasons, "evidence_revoked")
		} else if ex := parseTime(ev["expires_at"]); !ex.IsZero() && snapshot.After(ex) {
			freshness = map[string]any{"state": "expired", "detail": fmt.Sprintf("expired %d days ago", int(snapshot.Sub(ex).Hours()/24)), "days_expired": int(snapshot.Sub(ex).Hours() / 24)}
			if local < 1 {
				local = 1
			}
			reasons = append(reasons, "evidence_expired")
		} else if vf := parseTime(ev["valid_from"]); !vf.IsZero() && snapshot.Before(vf) {
			days := int(vf.Sub(snapshot).Hours() / 24)
			freshness = map[string]any{"state": "not_yet_valid", "detail": fmt.Sprintf("does not take effect for another %d days", days), "days_until_valid": days}
			if local < 1 {
				local = 1
			}
			reasons = append(reasons, "evidence_not_yet_valid")
		} else if ex := parseTime(ev["expires_at"]); !ex.IsZero() {
			freshness = map[string]any{"state": "current", "detail": fmt.Sprintf("valid for a further %d days", int(ex.Sub(snapshot).Hours()/24)), "days_until_expiry": int(ex.Sub(snapshot).Hours() / 24)}
		}
		findings = append(findings, map[string]any{"evidence_ref": r, "integrity": integ, "freshness": freshness})
		if local > worst {
			worst = local
		}
		if str(freshness["state"]) != "current" {
			desc = append(desc, r+" validity: "+str(freshness["detail"]))
		}
	}
	if len(refs) == 0 {
		checks = append(checks, check("evidence_freshness", "Evidence validity and integrity", "incomplete", "incomplete", "There is no evidence whose validity could be checked.", []string{"no_evidence_to_assess"}, nil, nil))
	} else {
		out, severity := "pass", "informational"
		if worst == 1 {
			out, severity = "review", "policy_dependent"
		}
		if worst == 2 {
			out, severity = "incomplete", "incomplete"
		}
		if worst >= 3 {
			out, severity = "fail", "hard_stop"
		}
		detail := fmt.Sprintf("All %d evidence record(s) have verified signed bindings and are current at %s.", len(refs), snapshot.Format("2006-01-02"))
		if len(desc) > 0 {
			detail = strings.Join(desc, "; ") + "."
		}
		checks = append(checks, check("evidence_freshness", "Evidence validity and integrity", out, severity, detail, uniqueStrings(reasons), refs, findings))
	}
	claims := arr(subject["claims"])
	requiredClaims := stringSlice(s.category(cat)["required_claim_types"])
	claimTypes := map[string]bool{}
	rejected := false
	outScope := false
	for _, cv := range claims {
		c := obj(cv)
		claimTypes[str(c["type"])] = true
		if st := str(c["state"]); st == "rejected" || st == "revoked" {
			rejected = true
		}
		iss := s.issuer(str(c["issuer_ref"]))
		if iss != nil && !contains(stringSlice(iss["authority_scopes"]), str(c["type"])) {
			outScope = true
		}
	}
	missClaims := []string{}
	for _, r := range requiredClaims {
		if !claimTypes[r] {
			missClaims = append(missClaims, r)
		}
	}
	if rejected {
		checks = append(checks, check("claims_and_category", "Claims and category requirements", "fail", "hard_stop", "A claim was rejected or revoked by its issuer.", []string{"claim_rejected_or_revoked"}, refs, nil))
	} else if len(missClaims) > 0 {
		checks = append(checks, check("claims_and_category", "Claims and category requirements", "incomplete", "incomplete", "No issuer has asserted the required claim(s): "+strings.Join(missClaims, ", ")+".", []string{"required_claim_missing"}, refs, nil))
	} else if outScope {
		checks = append(checks, check("claims_and_category", "Claims and category requirements", "review", "policy_dependent", "A claim was asserted outside the issuer's registered authority.", []string{"claim_asserted_outside_issuer_authority"}, refs, nil))
	} else {
		checks = append(checks, check("claims_and_category", "Claims and category requirements", "pass", "informational", fmt.Sprintf("All %d required claim type(s) present and asserted within issuer authority.", len(requiredClaims)), nil, refs, nil))
	}
	byType := map[string]map[string]bool{}
	for _, cv := range claims {
		c := obj(cv)
		t := str(c["type"])
		if byType[t] == nil {
			byType[t] = map[string]bool{}
		}
		byType[t][strings.ToLower(strings.TrimSpace(str(c["value"])))] = true
	}
	conflict := false
	for _, vals := range byType {
		if len(vals) > 1 {
			conflict = true
		}
	}
	if conflict {
		checks = append(checks, check("conflicting_information", "Conflicting information", "review", "policy_dependent", "Issuers disagree on a claim value.", []string{"issuers_state_conflicting_values"}, refs, nil))
	} else if len(claims) == 0 {
		checks = append(checks, check("conflicting_information", "Conflicting information", "incomplete", "incomplete", "There are no claims to compare.", []string{"no_claims_to_compare"}, nil, nil))
	} else {
		checks = append(checks, check("conflicting_information", "Conflicting information", "pass", "informational", "No two issuers state different values for the same claim type.", nil, nil, nil))
	}
	return s.verifyResult(subjectRef, checks, claims)
}

func (s *Server) verifyResult(ref string, checks []map[string]any, claims []any) map[string]any {
	pack := s.policyPack()
	claimResults := []map[string]any{}
	subject := s.seed.Subject(ref)
	snapshot := parseTime(obj(s.seedMap()["meta"])["snapshot_date"])
	for _, cv := range claims {
		c := obj(cv)
		verdict := "accepted"
		rs := []string{}
		severe := false
		revoked := false
		if st := str(c["state"]); st == "rejected" || st == "revoked" {
			verdict = st
			if reason := str(c["reason"]); reason != "" {
				rs = append(rs, reason)
			}
		} else if len(stringSlice(c["evidence_refs"])) == 0 {
			verdict = "rejected"
			rs = append(rs, "claim_evidence_missing")
		} else {
			for _, er := range stringSlice(c["evidence_refs"]) {
				ev := s.evidence(er)
				if ev == nil {
					rs = append(rs, "evidence_artefact_missing")
					severe = true
					continue
				}
				bindingOK := str(ev["subject_ref"]) == ref && str(ev["issuer_ref"]) == str(c["issuer_ref"])
				supported := []string{str(ev["claim_ref"])}
				supported = append(supported, stringSlice(ev["supports_claim_refs"])...)
				if !contains(supported, str(c["ref"])) {
					bindingOK = false
				}
				if !bindingOK {
					rs = append(rs, "claim_evidence_binding_invalid")
					severe = true
				}
				integ := s.evaluateEvidenceIntegrity(ev, ref, claims)
				if st := str(integ["state"]); st != "verified" {
					code := integrityReason[st]
					if code == "" {
						code = "evidence_integrity_unverified"
					}
					rs = append(rs, code)
					if st == "unsafe_path" || st == "hash_mismatch" || st == "signature_invalid" || st == "subject_scope_mismatch" || st == "artefact_binding_mismatch" {
						severe = true
					}
				}
				if st := str(ev["record_status"]); st == "revoked" || st == "withdrawn" {
					rs = append(rs, "evidence_revoked")
					revoked = true
					severe = true
				} else if ex := parseTime(ev["expires_at"]); !ex.IsZero() && snapshot.After(ex) {
					rs = append(rs, "evidence_expired")
				} else if vf := parseTime(ev["valid_from"]); !vf.IsZero() && snapshot.Before(vf) {
					rs = append(rs, "evidence_not_yet_valid")
				}
			}
			iss := s.issuer(str(c["issuer_ref"]))
			if iss == nil || str(iss["status"]) != "active" {
				rs = append(rs, "evidence_issuer_inactive")
				severe = true
			} else if !contains(stringSlice(iss["authority_scopes"]), str(c["type"])) {
				rs = append(rs, "asserted_outside_issuer_authority")
			}
			if revoked {
				verdict = "revoked"
			} else if severe {
				verdict = "rejected"
			} else if len(uniqueStrings(rs)) > 0 {
				verdict = "accepted_with_scope_limit"
			}
		}
		iss := s.issuer(str(c["issuer_ref"]))
		claimResults = append(claimResults, map[string]any{
			"claim_ref": c["ref"], "type": c["type"], "verdict": verdict, "value": valueOr(c, "value", ""),
			"issuer_ref": c["issuer_ref"], "issuer_name": valueOr(iss, "name", "unknown issuer"),
			"evidence_refs": stringSlice(c["evidence_refs"]), "reason_codes": uniqueStrings(rs),
		})
	}
	_ = subject
	return map[string]any{
		"subject_ref": ref, "policy_ref": pack["policy_ref"], "policy_version": pack["policy_version"], "policy_status": pack["status"],
		"policy_digest": s.fileDigest(filepath.Join(s.root, "data", "policy_pack_demo_v1.json")), "data_snapshot": s.seed.SnapshotID(),
		"dataset_digest": s.fileDigest(filepath.Join(s.root, "data", "demo_seed.json")), "check_results": checks, "claim_results": claimResults,
	}
}

var restrict = map[string]int{"allow": 0, "allow_with_warning": 1, "hold": 2, "escalate": 3, "block": 4}

func (s *Server) objective(checks []map[string]any, standing string) (string, int, int, string, []map[string]any, []string) {
	reasons := []string{}
	hasFail, hasHard, hasReview, hasIncomplete := false, false, false, false
	for _, c := range checks {
		switch str(c["outcome"]) {
		case "fail":
			hasFail = true
			if str(c["severity"]) == "hard_stop" {
				hasHard = true
			}
		case "review":
			hasReview = true
		case "incomplete":
			hasIncomplete = true
		}
		reasons = append(reasons, stringSlice(c["reason_codes"])...)
	}
	type cond struct {
		rule          int
		text, posture string
		met           bool
	}
	conds := []cond{{1, "standing is recalled", "block", standing == "recalled"}, {2, "a check failed with hard_stop severity", "block", hasHard}, {3, "standing is advisory", "hold", standing == "advisory"}, {4, "a check needs review, none failed or is incomplete, standing clean", "allow_with_warning", hasReview && !hasFail && !hasIncomplete && standing == "no_active_recall"}, {5, "every check passed and standing is clean", "allow", !hasFail && !hasReview && !hasIncomplete && standing == "no_active_recall"}, {6, "evidence or claims are incomplete", "escalate", hasIncomplete}}
	matched := []map[string]any{}
	primary := cond{6, "no rule matched; defaulted to escalate", "escalate", true}
	strict := primary
	first := true
	for _, c := range conds {
		if c.met {
			if first {
				primary = c
				strict = c
				first = false
			}
			if restrict[c.posture] > restrict[strict.posture] {
				strict = c
			}
			matched = append(matched, map[string]any{"rule": c.rule, "condition": c.text, "posture": c.posture})
		}
	}
	if first {
		matched = append(matched, map[string]any{"rule": 6, "condition": primary.text, "posture": "escalate"})
	}
	for _, m := range matched {
		m["is_primary_reason"] = intv(m["rule"]) == primary.rule
		m["determined_posture"] = intv(m["rule"]) == strict.rule
	}
	return strict.posture, strict.rule, primary.rule, primary.text, matched, uniqueStrings(reasons)
}

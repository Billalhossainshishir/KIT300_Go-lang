package ramify

import (
	"bufio"
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

var issuerPublicKeysHex = map[string]string{
	"ramify:demo:issuer:Concordia_Labs_AU": "1cc857a02abc5c386ff8dad04f7f5b61bfe075dde1739a18a61dd00922fe69c3",
	"ramify:demo:issuer:GMP_AU_demo":       "2b80c71d16b30042d72e5d7e9f35600fe36b1a2064323237b46c30e4c964032a",
	"ramify:demo:issuer:Regulator_AU_demo": "3b633daf869fd8fcbcced3f707a69c201c4e3d01410c07fb9473a9100f8a75e2",
}

var integrityReason = map[string]string{
	"missing_metadata":          "evidence_integrity_metadata_missing",
	"artefact_missing":          "evidence_artefact_missing",
	"unknown_issuer_key":        "evidence_issuer_key_unknown",
	"unsafe_path":               "evidence_storage_path_invalid",
	"hash_mismatch":             "evidence_hash_mismatch",
	"signature_invalid":         "evidence_signature_invalid",
	"subject_scope_mismatch":    "evidence_subject_scope_mismatch",
	"artefact_binding_mismatch": "evidence_artefact_binding_mismatch",
}

func evidenceBindingPayload(record map[string]any, subjectClaims []any) map[string]any {
	metadata := map[string]any{}
	for k, v := range record {
		if k == "content_hash" || k == "signature" || k == "storage_path" {
			continue
		}
		metadata[k] = v
	}
	refs := []string{}
	if ref := str(record["claim_ref"]); ref != "" {
		refs = append(refs, ref)
	}
	refs = append(refs, stringSlice(record["supports_claim_refs"])...)
	refs = uniqueStrings(refs)
	sort.Strings(refs)
	claimsByRef := map[string]map[string]any{}
	for _, cv := range subjectClaims {
		c := obj(cv)
		if ref := str(c["ref"]); ref != "" {
			claimsByRef[ref] = c
		}
	}
	supported := map[string]any{}
	for _, ref := range refs {
		c := claimsByRef[ref]
		if c == nil {
			supported[ref] = nil
			continue
		}
		supported[ref] = map[string]any{
			"ref": c["ref"], "type": c["type"], "issuer_ref": c["issuer_ref"], "state": c["state"], "value": valueOr(c, "value", nil),
		}
	}
	return map[string]any{"schema": "ramify-evidence-binding-v2", "record": metadata, "supported_claims": supported}
}

func canonicalJSONValue(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}

func (s *Server) evaluateEvidenceIntegrityBytes(record map[string]any, artefact []byte, expectedSubject string, subjectClaims []any) map[string]any {
	missing := []string{}
	for _, field := range []string{"content_hash", "signature", "issuer_ref", "subject_ref"} {
		if str(record[field]) == "" {
			missing = append(missing, field)
		}
	}
	if len(missing) > 0 {
		return map[string]any{"state": "missing_metadata", "detail": "integrity metadata missing: " + strings.Join(missing, ", ")}
	}
	digest := sha256.Sum256(artefact)
	computed := "sha256:" + hex.EncodeToString(digest[:])
	if computed != str(record["content_hash"]) {
		return map[string]any{"state": "hash_mismatch", "detail": "artefact bytes do not match the signed content hash", "computed_hash": computed}
	}
	hexKey, ok := issuerPublicKeysHex[str(record["issuer_ref"])]
	if !ok {
		return map[string]any{"state": "unknown_issuer_key", "detail": "issuer public key is not in the embedded trust material"}
	}
	keyBytes, err := hex.DecodeString(hexKey)
	if err != nil || len(keyBytes) != ed25519.PublicKeySize {
		return map[string]any{"state": "unknown_issuer_key", "detail": "issuer public key is not in the embedded trust material"}
	}
	sig, err := base64.StdEncoding.DecodeString(str(record["signature"]))
	if err != nil || !ed25519.Verify(ed25519.PublicKey(keyBytes), digest[:], sig) {
		return map[string]any{"state": "signature_invalid", "detail": "issuer Ed25519 signature does not verify"}
	}

	var signedBinding any
	scanner := bufio.NewScanner(bytes.NewReader(artefact))
	for i := 0; i < 6 && scanner.Scan(); i++ {
		line := scanner.Text()
		if strings.HasPrefix(line, "binding-json: ") {
			if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "binding-json: ")), &signedBinding); err != nil {
				return map[string]any{"state": "artefact_binding_mismatch", "detail": "signed artefact metadata binding is malformed"}
			}
			break
		}
	}
	if signedBinding == nil {
		return map[string]any{"state": "artefact_binding_mismatch", "detail": "signed artefact does not contain the required v2 metadata binding"}
	}
	expected := evidenceBindingPayload(record, subjectClaims)
	if !bytes.Equal(canonicalJSONValue(signedBinding), canonicalJSONValue(expected)) {
		return map[string]any{"state": "artefact_binding_mismatch", "detail": "signed evidence binding disagrees with structured metadata or supported claim values"}
	}

	expectedRef := expectedSubject
	if expectedRef == "" {
		expectedRef = str(record["subject_ref"])
	}
	scope := obj(record["scope"])
	scopedProduct := str(scope["product_ref"])
	if str(record["subject_ref"]) != expectedRef || (scopedProduct != "" && scopedProduct != expectedRef) {
		return map[string]any{"state": "subject_scope_mismatch", "detail": "evidence subject/scope does not match the assessed subject"}
	}
	return map[string]any{"state": "verified", "detail": "artefact hash and issuer Ed25519 signature verify; signed metadata/claim binding is consistent", "content_hash": computed}
}

func (s *Server) evaluateEvidenceIntegrity(record map[string]any, expectedSubject string, subjectClaims []any) map[string]any {
	storagePath := str(record["storage_path"])
	if storagePath == "" {
		return map[string]any{"state": "missing_metadata", "detail": "integrity metadata missing: storage_path"}
	}
	root := filepath.Clean(filepath.Join(s.root, "data"))
	path := filepath.Clean(filepath.Join(root, storagePath))
	rel, err := filepath.Rel(root, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return map[string]any{"state": "unsafe_path", "detail": "artefact storage path escapes the demo data directory"}
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return map[string]any{"state": "artefact_missing", "detail": fmt.Sprintf("artefact is missing: %s", storagePath)}
	}
	return s.evaluateEvidenceIntegrityBytes(record, b, expectedSubject, subjectClaims)
}

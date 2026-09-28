package ramify

import (
	"archive/zip"
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

type proofExample struct {
	Label, SubjectRef, ActorRef string
}

var quickProofExamples = []proofExample{
	{"01_APPROVED_Apex", "ramify:demo:supp:apex-mg-glyc-120", "consumer_v1"},
	{"02_EXPIRED_Evidence", "ramify:demo:supp:greenline-ashw-ksm66-90", "consumer_v1"},
	{"03_SELLER_RISK", "ramify:demo:ppe:covelane-n95-resp-b2026-01-B", "consumer_v1"},
	{"04_RECALL_Block", "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "consumer_v1"},
	{"05_SUBSTITUTION", "ramify:demo:supp:stonefield-zinc-gluc-50-90", "consumer_v1"},
}

var extendedProofExamples = []proofExample{
	{"allow", "ramify:demo:supp:apex-mg-glyc-120", "consumer_v1"},
	{"block-recall", "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "consumer_v1"},
	{"hold-advisory", "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z", "consumer_v1"},
	{"proof-consumer", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "consumer_v1"},
	{"proof-procurement", "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A", "procurement_v1"},
	{"warned", "ramify:demo:supp:greenline-ashw-ksm66-90", "consumer_v1"},
}

func sha256File(path string) string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	h := sha256.Sum256(raw)
	return "sha256:" + hex.EncodeToString(h[:])
}

func proofPublicKeys() map[string]string {
	out := map[string]string{}
	for ref, key := range issuerPublicKeysHex {
		out[ref] = key
	}
	state.mu.Lock()
	out[ramifySignerRef] = hex.EncodeToString(state.pub)
	state.mu.Unlock()
	return out
}

func canonicalProofManifest(manifest map[string]any) []byte {
	body := copyMap(manifest)
	delete(body, "manifest_signature")
	raw, _ := json.Marshal(body)
	return raw
}

func signProofManifest(manifest map[string]any) map[string]any {
	digest := sha256.Sum256(canonicalProofManifest(manifest))
	state.mu.Lock()
	priv := append(ed25519.PrivateKey(nil), state.priv...)
	state.mu.Unlock()
	out := copyMap(manifest)
	out["manifest_signature"] = base64.StdEncoding.EncodeToString(ed25519.Sign(priv, digest[:]))
	return out
}

func verifyProofManifest(manifest map[string]any, pub ed25519.PublicKey) bool {
	sig, err := base64.StdEncoding.DecodeString(str(manifest["manifest_signature"]))
	if err != nil || len(pub) != ed25519.PublicKeySize {
		return false
	}
	digest := sha256.Sum256(canonicalProofManifest(manifest))
	return ed25519.Verify(pub, digest[:], sig)
}

func zipWriteBytes(zw *zip.Writer, name string, raw []byte) error {
	w, err := zw.Create(name)
	if err != nil {
		return err
	}
	_, err = w.Write(raw)
	return err
}

func zipWriteJSON(zw *zip.Writer, name string, value any) error {
	b, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return zipWriteBytes(zw, name, append(b, '\n'))
}

func (s *Server) addProofEvidence(zw *zip.Writer) error {
	for _, rel := range []struct{ src, dst string }{
		{filepath.Join("data", "evidence_signatures.json"), filepath.Join("evidence", "evidence_signatures.json")},
		{filepath.Join("data", "record_signatures.json"), filepath.Join("evidence", "record_signatures.json")},
		{filepath.Join("data", "policy_pack_demo_v1.json"), filepath.Join("policy", "policy_pack_demo_v1.json")},
	} {
		raw, err := os.ReadFile(filepath.Join(s.root, rel.src))
		if err != nil {
			return err
		}
		if err := zipWriteBytes(zw, filepath.ToSlash(rel.dst), raw); err != nil {
			return err
		}
	}
	root := filepath.Join(s.root, "data", "artefacts")
	entries, err := os.ReadDir(root)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(root, entry.Name()))
		if err != nil {
			return err
		}
		if err := zipWriteBytes(zw, "evidence/artefacts/"+entry.Name(), raw); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) buildProofPack(examples []proofExample, packType string, includeReleaseEvidence bool) ([]byte, error) {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	receipts := make([]map[string]any, 0, len(examples))
	entries := make([]map[string]any, 0, len(examples))
	for _, ex := range examples {
		out, err := s.assessOne(ex.SubjectRef, ex.ActorRef, "", 1, "proof_pack", false)
		if err != nil {
			_ = zw.Close()
			return nil, err
		}
		receipt := obj(out["receipt"])
		receipts = append(receipts, receipt)
		filename := "receipts/" + ex.Label + "_" + strings.ReplaceAll(str(receipt["receipt_id"]), ":", "-") + ".json"
		raw, err := json.MarshalIndent(receipt, "", "  ")
		if err != nil {
			_ = zw.Close()
			return nil, err
		}
		raw = append(raw, '\n')
		if err := zipWriteBytes(zw, filename, raw); err != nil {
			_ = zw.Close()
			return nil, err
		}
		h := sha256.Sum256(raw)
		entries = append(entries, map[string]any{
			"filename": filename, "sha256": "sha256:" + hex.EncodeToString(h[:]), "receipt_id": receipt["receipt_id"],
		})
	}
	publicKeys := proofPublicKeys()
	signerBytes, _ := hex.DecodeString(publicKeys["ramify:demo:signer:receipt"])
	signerHash := sha256.Sum256(signerBytes)
	manifest := map[string]any{
		"schema": "ramify-proof-pack-manifest-v1", "pack_type": packType, "app_version": s.version,
		"data_snapshot": s.seed.SnapshotID(), "dataset_digest": s.datasetDigest(),
		"policy_ref": str(s.policyPack()["policy_ref"]), "policy_digest": sha256File(filepath.Join(s.root, "data", "policy_pack_demo_v1.json")),
		"verifier_version": "portable-go-verify-v2", "signer_key_fingerprint": "sha256:" + hex.EncodeToString(signerHash[:]),
		"expected_receipts":  entries,
		"verification_scope": "Historical sealed-record integrity against included public demonstration keys; not current purchase authority or evidence revalidation.",
	}
	manifest = signProofManifest(manifest)
	if err := zipWriteJSON(zw, "manifest.json", manifest); err != nil {
		return nil, err
	}
	index := make([]map[string]any, 0, len(receipts))
	for _, r := range receipts {
		index = append(index, map[string]any{
			"receipt_id": r["receipt_id"], "subject_ref": r["subject_ref"], "product_name": r["product_name"],
			"objective_posture": r["objective_posture"], "actor_decision": r["actor_decision"], "payload_hash": r["payload_hash"],
		})
	}
	if err := zipWriteJSON(zw, "receipt_index.json", index); err != nil {
		return nil, err
	}
	if err := zipWriteJSON(zw, "trust/public_keys.json", publicKeys); err != nil {
		return nil, err
	}
	if err := s.addProofEvidence(zw); err != nil {
		return nil, err
	}
	if err := zipWriteBytes(zw, "verify_receipts.go", []byte(portableProofVerifier)); err != nil {
		return nil, err
	}
	readme := fmt.Sprintf("RAMIFY OS %s Proof Pack\nVersion: %s\nData snapshot: %s\nReceipts: %d\nSigner fingerprint: %s\n\nSynthetic demonstration evidence only. These receipts do not certify a real product, seller, regulator or laboratory.\nThe manifest declares the expected files, build/data/policy identity, verifier version and signer-key fingerprint, and is signed by the same runtime signer as the receipts.\nA proof pack cannot vouch for its own included signer key. Compare this fingerprint with GET /healthz on the issuing RAMIFY instance before attributing authorship.\nPortable verification (Go 1.23+): go run verify_receipts.go\nSuccessful verification establishes historical sealed-record integrity, not current purchase authority.\n", strings.Title(packType), s.version, s.seed.SnapshotID(), len(receipts), manifest["signer_key_fingerprint"])
	if err := zipWriteBytes(zw, "README.txt", []byte(readme)); err != nil {
		return nil, err
	}
	if includeReleaseEvidence {
		for _, rel := range []string{"ASSESSMENT_EVIDENCE.json", "MEETING_RELEASE_EVIDENCE.txt", "DAVID_FEEDBACK_COVERAGE_MATRIX.md", "DAVID_LIVE_DEMO_GUIDE.md", "GO_FASTAPI_PARITY_MERGE_25_SEP_2026.md", "RELEASE_VALIDATION.txt", "FINAL_RELEASE_SUMMARY_25_SEP_2026.md", "FINAL_RELEASE_SUMMARY_29_SEP_2026.md", filepath.Join("docs", "07_21Sep_Final_Hardening_Addendum.md")} {
			path := filepath.Join(s.root, rel)
			raw, err := os.ReadFile(path)
			if err != nil {
				continue
			}
			dst := rel
			if strings.HasPrefix(rel, "docs"+string(filepath.Separator)) {
				dst = filepath.ToSlash(rel)
			} else if strings.HasSuffix(rel, ".md") {
				dst = "docs/" + filepath.Base(rel)
			}
			if err := zipWriteBytes(zw, filepath.ToSlash(dst), raw); err != nil {
				return nil, err
			}
		}
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func (s *Server) proofPackHTTP(w http.ResponseWriter, r *http.Request) {
	raw, err := s.buildProofPack(quickProofExamples, "quick", false)
	if err != nil {
		writeJSON(w, 500, map[string]any{"detail": err.Error()})
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="RAMIFY-Quick-Proof-Pack.zip"`)
	w.WriteHeader(200)
	_, _ = w.Write(raw)
}

func (s *Server) extendedProofPackHTTP(w http.ResponseWriter, r *http.Request) {
	raw, err := s.buildProofPack(extendedProofExamples, "extended", true)
	if err != nil {
		writeJSON(w, 500, map[string]any{"detail": err.Error()})
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="RAMIFY-Extended-Proof-Pack.zip"`)
	w.WriteHeader(200)
	_, _ = w.Write(raw)
}

// portableProofVerifier intentionally depends only on the Go standard library.
// It verifies the canonical receipt payload hash and Ed25519 signature against
// the public RAMIFY signer shipped inside the proof pack.
const portableProofVerifier = `package main

import (
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

const signerRef = "ramify:demo:signer:receipt"
const verifierVersion = "portable-go-verify-v2"

func readObject(path string) (map[string]any, error) {
  raw, err := os.ReadFile(path); if err != nil { return nil, err }
  var out map[string]any
  dec := json.NewDecoder(bytes.NewReader(raw)); dec.UseNumber()
  if err := dec.Decode(&out); err != nil { return nil, err }
  return out, nil
}
func canonicalReceipt(m map[string]any) []byte {
  c := make(map[string]any, len(m))
  for k,v := range m { if k != "payload_hash" && k != "signature" { c[k]=v } }
  b,_ := json.Marshal(c); return b
}
func canonicalManifest(m map[string]any) []byte {
  c := make(map[string]any, len(m))
  for k,v := range m { if k != "manifest_signature" { c[k]=v } }
  b,_ := json.Marshal(c); return b
}
func fingerprint(key []byte) string {
  h := sha256.Sum256(key); return "sha256:"+hex.EncodeToString(h[:])
}
func fail(msg string) {
  fmt.Println("FAIL", msg); os.Exit(2)
}
func main() {
  manifest, err := readObject("manifest.json"); if err != nil { fail("package metadata: manifest.json: "+err.Error()) }
  if fmt.Sprint(manifest["schema"]) != "ramify-proof-pack-manifest-v1" { fail("package metadata: unsupported manifest schema") }
  if fmt.Sprint(manifest["verifier_version"]) != verifierVersion { fail("package metadata: manifest verifier_version does not match this verifier") }

  keys, err := readObject(filepath.Join("trust","public_keys.json")); if err != nil { fail("package metadata: "+err.Error()) }
  keyHex, _ := keys[signerRef].(string)
  key, err := hex.DecodeString(keyHex); if err != nil || len(key) != ed25519.PublicKeySize { fail("package metadata: invalid signer public key") }
  fp := fingerprint(key)
  if fmt.Sprint(manifest["signer_key_fingerprint"]) != fp { fail("package metadata: signer-key fingerprint does not match trust/public_keys.json") }

  msig, err := base64.StdEncoding.DecodeString(fmt.Sprint(manifest["manifest_signature"]))
  mdigest := sha256.Sum256(canonicalManifest(manifest))
  if err != nil || !ed25519.Verify(ed25519.PublicKey(key), mdigest[:], msig) { fail("package metadata: manifest signature does not verify") }

  rows, ok := manifest["expected_receipts"].([]any); if !ok || len(rows)==0 { fail("package metadata: expected_receipts must be a non-empty list") }
  expected := map[string]map[string]any{}
  for _, raw := range rows {
    row, ok := raw.(map[string]any); if !ok { fail("package metadata: invalid receipt entry") }
    name := filepath.ToSlash(fmt.Sprint(row["filename"]))
    if !strings.HasPrefix(name, "receipts/") || strings.Contains(name, "..") || fmt.Sprint(row["sha256"]) == "" { fail("package metadata: invalid declared receipt") }
    expected[name] = row
  }

  files, _ := filepath.Glob(filepath.Join("receipts","*.json"))
  actual := map[string]bool{}
  for _, path := range files { actual[filepath.ToSlash(path)] = true }
  missing, unexpected := []string{}, []string{}
  for name := range expected { if !actual[name] { missing=append(missing,name) } }
  for name := range actual { if expected[name]==nil { unexpected=append(unexpected,name) } }
  sort.Strings(missing); sort.Strings(unexpected)
  if len(missing)>0 { fail("package completeness: missing expected receipt(s): "+strings.Join(missing,", ")) }
  if len(unexpected)>0 { fail("package completeness: unexpected receipt(s): "+strings.Join(unexpected,", ")) }

  fmt.Println("Signer key",fp)
  fmt.Println("This key came from the pack itself. Compare it with the issuing RAMIFY health fingerprint before attributing authorship.")
  failed := 0
  names := make([]string,0,len(expected)); for name := range expected { names=append(names,name) }; sort.Strings(names)
  for _, name := range names {
    row := expected[name]
    raw, err := os.ReadFile(filepath.FromSlash(name)); if err != nil { fmt.Println("FAIL",name,err); failed++; continue }
    fileHash := sha256.Sum256(raw)
    if fmt.Sprint(row["sha256"]) != "sha256:"+hex.EncodeToString(fileHash[:]) { fmt.Println("FAIL",name,"raw file digest does not match manifest"); failed++; continue }
    var receipt map[string]any
    dec := json.NewDecoder(bytes.NewReader(raw)); dec.UseNumber()
    if err := dec.Decode(&receipt); err != nil { fmt.Println("FAIL",name,err); failed++; continue }
    digest := sha256.Sum256(canonicalReceipt(receipt))
    hashOK := fmt.Sprint(receipt["payload_hash"]) == "sha256:"+hex.EncodeToString(digest[:])
    sig, err := base64.StdEncoding.DecodeString(fmt.Sprint(receipt["signature"]))
    sigOK := err == nil && ed25519.Verify(ed25519.PublicKey(key), digest[:], sig)
    issuerOK := true
    if refs, ok := receipt["issuer_refs"].([]any); ok {
      for _, ref := range refs { if _, exists := keys[fmt.Sprint(ref)]; !exists { issuerOK=false } }
    }
    if hashOK && sigOK && issuerOK { fmt.Println("PASS",name) } else { fmt.Printf("FAIL %s hash=%v signature=%v issuers=%v\n",name,hashOK,sigOK,issuerOK); failed++ }
  }
  if failed > 0 { os.Exit(2) }
  fmt.Printf("PASS: %d receipt(s) verified. Historical integrity only; this does not establish current purchase authority.\n",len(expected))
}
`

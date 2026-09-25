package ramify

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
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
	out["ramify:demo:signer:receipt"] = hex.EncodeToString(state.pub)
	state.mu.Unlock()
	return out
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
		"data_snapshot": s.seed.SnapshotID(), "dataset_digest": sha256File(filepath.Join(s.root, "data", "demo_seed.json")),
		"policy_ref": str(s.policyPack()["policy_ref"]), "policy_digest": sha256File(filepath.Join(s.root, "data", "policy_pack_demo_v1.json")),
		"verifier_version": "portable-go-verify-v1", "signer_key_fingerprint": "sha256:" + hex.EncodeToString(signerHash[:]),
		"expected_receipts":  entries,
		"verification_scope": "Historical sealed-record integrity against included public demonstration keys; not current purchase authority or evidence revalidation.",
	}
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
	readme := fmt.Sprintf("RAMIFY OS %s Proof Pack\nVersion: %s\nData snapshot: %s\nReceipts: %d\n\nSynthetic demonstration evidence only. These receipts do not certify a real product, seller, regulator or laboratory.\nThe manifest declares expected receipt files, build/data/policy identity, verifier version and signer-key fingerprint.\nPortable verification (Go 1.23+): go run verify_receipts.go\nSuccessful verification establishes historical sealed-record integrity, not current purchase authority.\n", strings.Title(packType), s.version, s.seed.SnapshotID(), len(receipts))
	if err := zipWriteBytes(zw, "README.txt", []byte(readme)); err != nil {
		return nil, err
	}
	if includeReleaseEvidence {
		for _, rel := range []string{"ASSESSMENT_EVIDENCE.json", "MEETING_RELEASE_EVIDENCE.txt", "DAVID_FEEDBACK_COVERAGE_MATRIX.md", "DAVID_LIVE_DEMO_GUIDE.md", "GO_FASTAPI_PARITY_MERGE_25_SEP_2026.md", "RELEASE_VALIDATION.txt", "FINAL_RELEASE_SUMMARY_25_SEP_2026.md", filepath.Join("docs", "07_21Sep_Final_Hardening_Addendum.md")} {
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
)

func readObject(path string) (map[string]any, error) {
  raw, err := os.ReadFile(path); if err != nil { return nil, err }
  var out map[string]any
  dec := json.NewDecoder(bytes.NewReader(raw)); dec.UseNumber()
  if err := dec.Decode(&out); err != nil { return nil, err }
  return out, nil
}
func canonical(m map[string]any) []byte {
  c := make(map[string]any, len(m))
  for k,v := range m { if k != "payload_hash" && k != "signature" { c[k]=v } }
  b,_ := json.Marshal(c); return b
}
func main() {
  keys, err := readObject(filepath.Join("trust","public_keys.json")); if err != nil { fmt.Fprintln(os.Stderr, err); os.Exit(2) }
  keyHex, _ := keys["ramify:demo:signer:receipt"].(string)
  key, err := hex.DecodeString(keyHex); if err != nil || len(key) != ed25519.PublicKeySize { fmt.Fprintln(os.Stderr,"invalid signer public key"); os.Exit(2) }
  files, _ := filepath.Glob(filepath.Join("receipts","*.json")); if len(files)==0 { fmt.Fprintln(os.Stderr,"no receipts found"); os.Exit(2) }
  failed := 0
  for _, path := range files {
    receipt, err := readObject(path); if err != nil { fmt.Println("FAIL",path,err); failed++; continue }
    digest := sha256.Sum256(canonical(receipt))
    want := "sha256:"+hex.EncodeToString(digest[:])
    hashOK := receipt["payload_hash"] == want
    sig, err := base64.StdEncoding.DecodeString(fmt.Sprint(receipt["signature"]))
    sigOK := err == nil && ed25519.Verify(ed25519.PublicKey(key), digest[:], sig)
    if hashOK && sigOK { fmt.Println("PASS",path) } else { fmt.Printf("FAIL %s hash=%v signature=%v\n",path,hashOK,sigOK); failed++ }
  }
  if failed > 0 { os.Exit(1) }
  fmt.Printf("PASS: %d receipt(s) verified. Historical integrity only; this does not establish current purchase authority.\n",len(files))
}
`

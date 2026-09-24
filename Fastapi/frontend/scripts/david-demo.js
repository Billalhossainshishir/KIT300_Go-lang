"use strict";

const APEX = "ramify:demo:supp:apex-mg-glyc-120";
const NORTHBEAM = "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A";
const ADVISORY = "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z";
const RIDGEWAY = "ramify:demo:supp:ridgeway-multivit-b2026-02-C";
let clean = null;

const stateText = (value) => String(value || "—").replaceAll("_", " ");
const good = (value) => `<span class="meeting-status ok">${esc(value)}</span>`;
const warn = (value) => `<span class="meeting-status warn">${esc(value)}</span>`;
const bad = (value) => `<span class="meeting-status bad">${esc(value)}</span>`;

function evidenceSummary(receipt) {
  const check = (receipt?.check_results || []).find((item) => item.check_id === "evidence_freshness") || {};
  const findings = check.findings || [];
  const integrityStates = findings.map((item) => item.integrity?.state).filter(Boolean);
  const validityStates = findings.map((item) => item.freshness?.state || item.state).filter(Boolean);
  const hash = findings.map((item) => item.integrity?.content_hash).find(Boolean) || "";
  return {
    check,
    findings,
    integrity: integrityStates.length && integrityStates.every((state) => state === "verified") ? "Verified" : [...new Set(integrityStates)].join(", ") || "Not available",
    validity: validityStates.length && validityStates.every((state) => state === "current") ? "Current" : [...new Set(validityStates)].join(", ") || "Not available",
    hash,
  };
}

function traceHTML(result) {
  return `<div class="meeting-primitive-strip">${(result.call_trace || []).map((row, index) => `<span><small>0${index + 1}</small><b>${esc(row.primitive)}</b><em>${esc(stateText(row.output))}</em></span>`).join("<i>→</i>")}</div>`;
}

async function runClean() {
  const out = $("david-clean-output");
  out.innerHTML = `<p class="placeholder">Running deterministic assessment…</p>`;
  clean = await api("/api/v0/assess", {identifier: APEX, actor_ref: "consumer_v1", quantity: 1, context: "purchase"});
  const receiptReport = await api("/api/v0/receipt/verify", clean.receipt);
  const proof = evidenceSummary(clean.receipt);
  const integrityOK = proof.integrity === "Verified";
  const validityOK = proof.validity === "Current";
  out.innerHTML = `
    <div class="meeting-result-banner"><div><small>Product</small><b>${esc(clean.product_name)}</b></div><div><small>Objective product truth</small>${good(clean.objective_posture.toUpperCase())}</div><div><small>Actor decision</small>${good(clean.actor_decision.toUpperCase())}</div><div><small>Signed receipt</small>${receiptReport.verified ? good("VERIFIED") : bad("FAILED")}</div></div>
    ${traceHTML(clean)}
    <div class="evidence-proof-card meeting-evidence-card">
      <div class="evidence-proof-head"><div><span class="eyebrow">EVIDENCE PROOF</span><h3>Evidence integrity and evidence validity are evaluated separately.</h3></div>${integrityOK ? good("Integrity verified") : bad("Integrity problem")}</div>
      <div class="evidence-proof-grid">
        <span><small>Evidence Integrity</small><b>${esc(proof.integrity)}</b><em>Authentic and unchanged?</em></span>
        <span><small>SHA-256</small><b>${integrityOK ? "Matched" : "Failed"}</b><em>${esc(proof.hash ? proof.hash.slice(0, 24) + "…" : "—")}</em></span>
        <span><small>Ed25519 Signature</small><b>${integrityOK ? "Valid" : "Failed"}</b><em>Issuer public key used</em></span>
        <span><small>Issuer + Subject/Scope</small><b>${integrityOK ? "Verified / Matched" : "Check findings"}</b><em>Evidence bound to assessed subject</em></span>
        <span><small>Evidence Validity</small><b>${esc(proof.validity)}</b><em>${validityOK ? "Current at the fixed assessment snapshot" : "Date/status limits apply"}</em></span>
      </div>
      <details><summary>View RATIFY evidence findings</summary><pre>${esc(JSON.stringify(proof.findings, null, 2))}</pre></details>
    </div>`;
}

async function runEvidenceTamper() {
  const term = $("david-tamper-output"); term.hidden = false; term.classList.remove("bad"); term.textContent = "Running reversible evidence tamper…";
  try {
    const r = await api("/api/v0/demo/evidence-tamper", {subject_ref: APEX});
    term.classList.toggle("bad", r.tampered_integrity?.state === "verified" || !r.artefact_restored);
    term.textContent = [
      "$ evidence tamper proof",
      "",
      `clean integrity       ${r.clean_integrity?.state}`,
      `tampered integrity    ${r.tampered_integrity?.state}`,
      `RATIFY outcome        ${r.ratify_outcome}`,
      `objective posture     ${r.objective_posture}`,
      `reason code           ${(r.reason_codes || []).join(", ")}`,
      `shared artefact changed ${r.shared_artefact_modified ? "YES" : "no"}`,
      "",
      "Meaning: RATIFY rejected an isolated modified byte copy; the shared evidence file was never changed.",
    ].join("\n");
  } catch (e) { term.classList.add("bad"); term.textContent = e.message; }
}

async function runReceiptTamper() {
  if (!clean) await runClean();
  const term = $("david-tamper-output"); term.hidden = false;
  const copy = JSON.parse(JSON.stringify(clean.receipt));
  if (copy.order?.unit_price_cents != null) copy.order.unit_price_cents += 1;
  else copy.product_name += " [tampered]";
  const report = await api("/api/v0/receipt/verify", copy);
  term.classList.toggle("bad", report.verified);
  term.textContent = [
    "$ ramify-verify < tampered-receipt.json",
    "",
    ...report.checks.map((c) => `${c.name.padEnd(24)} ${c.passed ? "ok" : "FAIL"}  ${c.detail}`),
    "",
    report.verified ? "UNEXPECTED: tampered receipt verified" : "EXPECTED: RECEIPT DID NOT VERIFY.",
    "",
    "Evidence verification is before the trust decision; receipt verification protects the sealed decision after it is made.",
  ].join("\n");
}

async function runActors() {
  const out = $("david-actors-output"); out.innerHTML = `<p class="placeholder">Running both actors against the same product…</p>`;
  const r = await api("/api/v0/compare", {identifier: NORTHBEAM, quantity: 1, actor_refs: ["consumer_v1", "procurement_v1"]});
  const c = r.personas.find((x) => x.actor_ref === "consumer_v1");
  const p = r.personas.find((x) => x.actor_ref === "procurement_v1");
  out.innerHTML = `<div class="truth-lock"><small>Objective truth shared by both actors</small><strong>${esc(stateText(r.objective_posture).toUpperCase())}</strong><span>${r.objective_agreed ? "✓ identical objective result" : "✕ objective mismatch"}</span></div><div class="actor-proof-pair"><article><span>Consumer</span><b>${esc(stateText(c.decision).toUpperCase())}</b><p>${esc(stateText(c.selected_action))}</p></article><article><span>Procurement</span><b>${esc(stateText(p.decision).toUpperCase())}</b><p>${esc(stateText(p.selected_action))}</p></article></div><p class="detail-note">The product truth did not change. Procurement narrowed what it was authorised to do because the seller is outside its approved-vendor arrangement.</p>`;
}

async function runCheckout() {
  const out = $("david-checkout-output"); out.innerHTML = `<p class="placeholder">Running the isolated signed-authority checkout proof…</p>`;
  const proof = await api("/api/v0/demo/checkout-proof", {});
  const assessment = proof.assessment;
  const verify = proof.verification;
  const basket = proof.line;
  const checkout = proof.order;
  out.innerHTML = `<div class="trust-chain-proof"><span><small>1</small><b>Decision receipt</b><em>${esc(assessment.receipt_ref.slice(-12))}</em></span><i>→</i><span><small>2</small><b>Re-verified</b><em>${verify.purchase_authority_valid ? "current + intact" : "not valid"}</em></span><i>→</i><span><small>3</small><b>Demo-cart authority</b><em>${esc(basket.line_id?.slice(-12) || "admitted")}</em></span><i>→</i><span><small>4</small><b>Signed demo order</b><em>${esc(checkout.order_id?.slice(-12) || "created")}</em></span></div><p class="detail-note">Checkout re-reads the decision receipt and transaction-critical values. This proof uses a dedicated demo cart; the normal basket is not cleared or modified.</p>`;
}


async function runHuman() {
  const out = $("david-human-output"); out.innerHTML = `<p class="placeholder">Creating a fresh held purchase receipt…</p>`;
  const original = await api("/api/v0/assess", {identifier: ADVISORY, actor_ref: "consumer_v1", quantity: 1, context: "purchase"});
  const successor = await api("/api/v0/receipt/review", {receipt_id: original.receipt_ref, outcome: "overridden", reviewer_name: "David meeting demo", reviewer_role: "Authorised demo reviewer", reviewer_note: "Synthetic one-time approval to demonstrate successor lineage."});
  out.innerHTML = `<div class="lineage-proof"><article><small>Original machine receipt</small><b>${esc(original.receipt_ref)}</b><span>${warn(original.actor_decision.toUpperCase())}</span></article><i>→</i><article><small>Human review</small><b>Approved once</b><span>original unchanged</span></article><i>→</i><article><small>Signed successor</small><b>${esc(successor.receipt_ref)}</b><span>supersedes original</span></article></div><details><summary>View successor linkage</summary><pre>${esc(JSON.stringify({original_receipt: original.receipt_ref, successor_receipt: successor.receipt_ref, supersedes: successor.supersedes, human_review: successor.receipt.human_review}, null, 2))}</pre></details>`;
}

async function runIncomplete() {
  const out = $("david-incomplete-output"); out.innerHTML = `<p class="placeholder">Running incomplete-evidence and absent-status proofs…</p>`;
  const [r, absent] = await Promise.all([
    api("/api/v0/assess", {identifier: RIDGEWAY, actor_ref: "consumer_v1", quantity: 1, context: "guided_demo"}),
    api("/api/v0/demo/absent-status"),
  ]);
  const incomplete = (r.receipt.check_results || []).filter((x) => x.outcome === "incomplete");
  out.innerHTML = `<div class="meeting-result-banner"><div><small>Ridgeway recorded status</small><b>${esc(stateText(r.receipt.status_result?.standing))}</b></div><div><small>Objective posture</small>${warn(r.objective_posture.toUpperCase())}</div><div><small>Incomplete checks</small><b>${incomplete.length}</b></div><div><small>Separate absent-status probe</small><b>${esc(stateText(absent.standing))}</b></div></div><p class="detail-note"><strong>Two different cases are shown honestly.</strong> Ridgeway demonstrates incomplete evidence while retaining its explicit status record. The separate absent-status probe shows that genuinely missing status becomes <em>unknown</em>, not “no active recall”.</p><details><summary>View findings</summary><pre>${esc(JSON.stringify({ridgeway_incomplete: incomplete, absent_status: absent}, null, 2))}</pre></details>`;
}


async function boot() {
  mountShell("/david-demo"); mountFooter();
  try { const health = await api("/healthz"); $("david-build-id").textContent = health.build || "—"; } catch (_) {}
  $("david-clean").onclick = () => runClean().catch((e) => toast(e.message, "bad"));
  $("david-evidence-tamper").onclick = () => runEvidenceTamper().catch((e) => toast(e.message, "bad"));
  $("david-receipt-tamper").onclick = () => runReceiptTamper().catch((e) => toast(e.message, "bad"));
  $("david-actors").onclick = () => runActors().catch((e) => toast(e.message, "bad"));
  $("david-checkout").onclick = () => runCheckout().catch((e) => toast(e.message, "bad"));
  $("david-human").onclick = () => runHuman().catch((e) => toast(e.message, "bad"));
  $("david-incomplete").onclick = () => runIncomplete().catch((e) => toast(e.message, "bad"));
}
startPage(boot);

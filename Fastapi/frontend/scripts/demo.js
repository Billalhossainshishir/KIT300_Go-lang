"use strict";

const SHIPPED_PERSONA_REFS = Object.freeze(["consumer_v1", "autonomous_buyer_v1", "budget_guard_v1", "brand_loyal_v1", "procurement_v1"]);

let cat;
let currentStep = 0;
let result = null;
let interpretation = null;
let comparison = null;
let selectedScenario = null;
let selectedProduct = null;

const GUIDED_STEPS = [
  ["Choose", "What the shopper wants", "01", "⌁"],
  ["Understand", "Match the known product", "02", "⌁"],
  ["RAMIFY", "Check the product facts", "03", "✓"],
  ["Five policies", "Compare controlled actions", "04", "◇"],
  ["Next action", "Human or safe continuation", "05", "→"],
  ["Receipt", "Explain and prove the result", "06", "R"],
];

function msFromUs(value) {
  return `${(Number(value || 0) / 1000).toFixed(3)} ms`;
}

function humanRequest(product) {
  const seller = product?.seller_name ? ` from ${product.seller_name}` : "";
  return `Please check ${product?.name || "this product"}${seller} before I buy it.`;
}

async function boot() {
  mountShell("/demo");
  document.body.classList.add("guided-focus");
  mountFooter();
  cat = await catalogue();
  $("scenario").innerHTML = cat.scenarios
    .map((scenario) => `<option value="${esc(scenario.id)}">${esc(scenario.id)} · ${esc(scenario.note)}</option>`)
    .join("");
  $("scenario").addEventListener("change", updateScenarioPreview);
  updateScenarioPreview();
  $("run-demo").onclick = run;
  $("guided-back").onclick = () => go(Math.max(0, currentStep - 1));
  $("guided-next").onclick = () => go(Math.min(GUIDED_STEPS.length - 1, currentStep + 1));

  document.addEventListener("keydown", (event) => {
    if ($("walkthrough").hidden || event.altKey || event.ctrlKey || event.metaKey) return;
    const tag = document.activeElement?.tagName;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
    if (event.key === "ArrowRight" && currentStep < GUIDED_STEPS.length - 1) {
      event.preventDefault();
      go(currentStep + 1, { scroll: false });
    } else if (event.key === "ArrowLeft" && currentStep > 0) {
      event.preventDefault();
      go(currentStep - 1, { scroll: false });
    }
  });
}

function updateScenarioPreview() {
  const scenario = cat?.scenarios?.find((item) => item.id === $("scenario").value);
  const product = scenario ? cat.products.find((item) => item.subject_ref === scenario.subject_ref) : null;
  const preview = $("guided-scenario-preview");
  if (!preview || !scenario) return;
  preview.innerHTML = `
    <span class="guided-preview-label">Selected story</span>
    <strong>${esc(product?.name || scenario.id)}</strong>
    <small>${esc(scenario.note || "Synthetic acceptance scenario")}</small>`;
  preview.classList.remove("guided-preview-pulse");
  requestAnimationFrame(() => preview.classList.add("guided-preview-pulse"));
}

async function run() {
  selectedScenario = cat.scenarios.find((scenario) => scenario.id === $("scenario").value);
  if (!selectedScenario) return;
  selectedProduct = cat.products.find((p) => p.subject_ref === selectedScenario.subject_ref) || null;
  const requestText = humanRequest(selectedProduct);

  const button = $("run-demo");
  button.disabled = true;
  button.classList.add("is-loading");
  button.innerHTML = '<span class="guided-start-icon guided-spinner" aria-hidden="true"></span><span class="guided-start-copy">Preparing your walkthrough…</span><b>•••</b>';

  try {
    [interpretation, result, comparison] = await Promise.all([
      api("/api/v0/interpret", {
        request_text: requestText,
        actor_ref: selectedScenario.actor_ref,
        mode: "deterministic",
        candidate_refs: [selectedScenario.subject_ref],
      }),
      api("/api/v0/assess", {
        identifier: selectedScenario.subject_ref,
        actor_ref: selectedScenario.actor_ref,
        quantity: 1,
        context: "guided_demo",
      }),
      api("/api/v0/compare", {
        identifier: selectedScenario.subject_ref,
        quantity: 1,
        actor_refs: SHIPPED_PERSONA_REFS,
      }),
    ]);

    $("guided-empty").hidden = true;
    $("walkthrough").hidden = false;
    currentStep = 0;
    render();
    $("walkthrough").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message, "bad");
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.innerHTML = '<span class="guided-start-icon" aria-hidden="true">▶</span><span class="guided-start-copy">Start guided demo</span><b>→</b>';
  }
}

function renderRail() {
  $("guided-steps").innerHTML = GUIDED_STEPS.map(([title, sub, number, icon], index) => `
    <button type="button" data-guided-step="${index}" class="guided-step ${index === currentStep ? "active" : index < currentStep ? "done" : ""}" aria-current="${index === currentStep ? "step" : "false"}">
      <span class="guided-step-orb"><i>${esc(index < currentStep ? "✓" : icon)}</i><em>${esc(number)}</em></span>
      <div><strong>${esc(title)}</strong><small>${esc(sub)}</small></div>
      <b class="guided-step-chevron">›</b>
    </button>`).join("");

  $$('[data-guided-step]').forEach((button) => {
    const step = Number(button.dataset.guidedStep);
    button.disabled = step > currentStep;
    button.onclick = () => go(step);
  });
}

function resultTone(posture) {
  return posture === "block" ? "red" : ["allow_with_warning", "hold", "escalate"].includes(posture) ? "amber" : "green";
}

function evidenceProofSummary(receipt) {
  const check = (receipt?.check_results || []).find((item) => item.check_id === "evidence_freshness") || {};
  const findings = check.findings || [];
  const integrity = findings.map((item) => item.integrity?.state).filter(Boolean);
  const validity = findings.map((item) => item.freshness?.state || item.state).filter(Boolean);
  const firstHash = findings.map((item) => item.integrity?.content_hash).find(Boolean) || "";
  return {
    check,
    integrityVerified: integrity.length > 0 && integrity.every((state) => state === "verified"),
    validityLabel: validity.length && validity.every((state) => state === "current") ? "Current" : [...new Set(validity)].join(", ").replaceAll("_", " ") || "Not available",
    hash: firstHash,
    count: findings.length,
  };
}

function shortHash(value) {
  const text = String(value || "");
  if (!text) return "—";
  return text.length > 30 ? `${text.slice(0, 20)}…${text.slice(-8)}` : text;
}

function renderRequest() {
  return `
    <div class="guided-stage-kicker">STEP 1 · USER REQUEST</div>
    <div class="guided-stage-number">01</div>
    <h2>Start with the shopper, not the technology.</h2>
    <p class="guided-stage-lede">The user only needs to describe what they want to buy. RAMIFY takes care of the checking behind the scenes.</p>
    <div class="guided-request-card">
      <div class="guided-product-line">
        <div class="guided-product-mark guided-product-photo">
          <img src="${esc(productImage(selectedProduct?.subject_ref || result.subject_ref))}" alt="${esc(selectedProduct?.name || result.product_name)}">
        </div>
        <div><strong>${esc(selectedProduct?.name || result.product_name)}</strong><span>${esc(selectedProduct?.seller_name || result.order?.seller_name || "Synthetic seller")}</span></div>
        <b>${money(selectedProduct?.price_cents || result.order?.unit_price_cents)}</b>
      </div>
      <div class="guided-request-copy"><span>Plain-English request</span><blockquote>${esc(humanRequest(selectedProduct))}</blockquote></div>
      <div class="guided-context-row">
        <span>Starting agent <strong>${esc(result.actor_label)}</strong></span>
        <span>Scenario <strong>${esc(selectedScenario.id)}</strong></span>
      </div>
    </div>`;
}

function renderInterpretation() {
  const source = agentSourceLabel(interpretation?.source);
  const confidence = interpretation?.confidence != null ? `${Math.round(Number(interpretation.confidence) * 100)}% match` : "Known catalogue match";
  return `
    <div class="guided-stage-kicker">STEP 2 · WHAT DID AI UNDERSTAND?</div>
    <div class="guided-stage-number">02</div>
    <h2>AI turns everyday language into structured fields.</h2>
    <p class="guided-stage-lede">This scripted client walkthrough uses RAMIFY's fast deterministic catalogue matcher, so it does not wait for Llama. The live Shop can use local Llama 3.1 for free-form requests. Neither interpretation path can approve or reject anything.</p>
    <div class="guided-structured">
      <div class="guided-structured-head"><div><span>Structured request</span><strong>The request is ready for deterministic verification.</strong></div><span class="guided-match">${esc(confidence)}</span></div>
      <div class="guided-field-grid">
        <span><small>Product</small><b>${esc(selectedProduct?.name || result.product_name)}</b></span>
        <span><small>Brand</small><b>${esc(selectedProduct?.brand || result.order?.brand || "—")}</b></span>
        <span><small>Batch / model</small><b>${esc(selectedProduct?.batch_ref || result.order?.batch_ref || "—")}</b></span>
        <span><small>Seller</small><b>${esc(selectedProduct?.seller_name || result.order?.seller_name || "—")}</b></span>
        <span><small>Source</small><b>${esc(source)}</b></span>
      </div>
      <div class="guided-boundary"><span>Interpretation responsibility</span><strong>Identify the intended catalogue item</strong><span>RAMIFY responsibility</span><strong>Decide trust deterministically</strong></div>
    </div>`;
}

function renderChecks() {
  const rows = result.call_trace || [];
  const totalUs = result.receipt?.latencies_us?.total || rows.reduce((sum, row) => sum + Number(row.latency_us || 0), 0);
  const tone = resultTone(result.objective_posture);
  return `
    <div class="guided-stage-kicker">STEP 3 · DETERMINISTIC PRODUCT CHECK</div>
    <div class="guided-stage-number">03</div>
    <h2>RAMIFY checks the facts before any agent policy is applied.</h2>
    <p class="guided-stage-lede">Identity, evidence, seller authority, status, claims and conflicts are evaluated by deterministic code. The measured time is shown beside each primitive.</p>
    <div class="guided-proof-banner tone-${tone}">
      <div><span>Objective product result</span><strong>${esc(result.objective_light?.label || result.objective_posture)}</strong><small>${esc(result.objective_posture)}</small></div>
      <div class="guided-total-time"><span>RAMIFY processing</span><strong>${msFromUs(totalUs)}</strong><small>this local run</small></div>
    </div>
    <div class="guided-trace">
      ${rows.map((row) => {
        const label = row.primitive === "status" ? (result.receipt?.status_result?.standing || "checked") : row.primitive === "assess" ? result.objective_posture : "complete";
        return `<div><code>${esc(row.primitive)}()</code><span>${esc(label.replaceAll("_", " "))}</span><b>${msFromUs(row.latency_us)}</b></div>`;
      }).join("")}
    </div>
    ${(() => { const proof = evidenceProofSummary(result.receipt); return `
      <section class="evidence-proof-card">
        <div class="evidence-proof-head"><div><span class="eyebrow">EVIDENCE VERIFICATION</span><h3>Integrity and validity are different questions.</h3></div><span class="evidence-proof-badge ${proof.integrityVerified ? "ok" : "bad"}">${proof.integrityVerified ? "Integrity verified" : "Integrity not verified"}</span></div>
        <div class="evidence-proof-grid">
          <span><small>Evidence Integrity</small><b>${proof.integrityVerified ? "Verified" : "Not verified"}</b><em>Is the artefact authentic and unchanged?</em></span>
          <span><small>SHA-256</small><b>${proof.integrityVerified ? "Matched" : "Check findings"}</b><em>${esc(shortHash(proof.hash))}</em></span>
          <span><small>Ed25519 signature</small><b>${proof.integrityVerified ? "Valid" : "Check findings"}</b><em>Issuer public-key verification</em></span>
          <span><small>Issuer + subject/scope</small><b>${proof.integrityVerified ? "Verified / matched" : "Check findings"}</b><em>Signed artefact is bound to this subject</em></span>
          <span><small>Evidence Validity</small><b>${esc(proof.validityLabel)}</b><em>Is it usable at the assessment snapshot?</em></span>
        </div>
        <details><summary>View technical evidence findings (${proof.count})</summary><pre>${esc(JSON.stringify(proof.check.findings || [], null, 2))}</pre></details>
        <div class="guided-finish-row"><button class="btn btn-ghost" type="button" id="guided-evidence-tamper">Run safe evidence-tamper proof</button></div>
        <div class="terminal" id="guided-evidence-terminal" hidden></div>
      </section>`; })()}
    <p class="guided-measure-note">These are local prototype measurements, not a production performance claim.</p>`;
}

function renderPolicies() {
  const selected = selectedScenario.actor_ref;
  return `
    <div class="guided-stage-kicker">STEP 4 · FIVE DELEGATED POLICY PROFILES</div>
    <div class="guided-stage-number">04</div>
    <h2>The facts stay fixed. Only the delegated action changes.</h2>
    <p class="guided-stage-lede">All five profiles receive the same objective result. Their own buying rules may make the next step stricter, but they cannot make product trust more permissive.</p>
    <div class="guided-locked-line"><strong>The evidence did not change.</strong><span>One locked objective result was shared with all five profiles.</span></div>
    <div class="guided-policy-grid">
      ${comparison.personas.map((persona) => `
        <article class="${persona.actor_ref === selected ? "selected " : ""}${personaClass(persona.actor_ref)}">
          <div class="guided-avatar">${esc(persona.actor_label.split(/\s+/).map((x) => x[0]).join("").slice(0, 2))}</div>
          <div><strong>${esc(persona.actor_label)}</strong><small>${esc(persona.summary || persona.autonomy || "Delegated policy")}</small></div>
          <span class="policy-outcome tone-${resultTone(persona.decision)}">${esc(persona.traffic_light?.label || persona.decision.replaceAll("_", " "))}</span>
        </article>`).join("")}
    </div>
    <div class="guided-selected-policy ${personaClass(result.actor_ref)}"><span>Selected for this story</span><strong><span class="persona-dot" aria-hidden="true"></span>${esc(result.actor_label)}</strong><b>${esc(result.actor_decision.replaceAll("_", " "))}</b></div>`;
}

function renderNextAction() {
  const needsHuman = ["hold", "escalate"].includes(result.actor_decision);
  const blocked = result.actor_decision === "block" || result.objective_posture === "block";
  const heading = blocked
    ? "The safe action is to stop."
    : needsHuman
      ? "In a purchase journey, the agent would pause for human review."
      : "The policy has selected a permitted next action.";
  const copy = blocked
    ? "A hard-stop finding stays attached to the product and cannot be bypassed by another agent or by human review."
    : needsHuman
      ? "Guided mode demonstrates this branch without creating a real Needs me task. A fresh purchase-context check in Shop would create the review task and any linked successor receipt."
      : "Guided mode shows what the Action Gate would permit, but it does not execute a basket or requisition transaction. Actual transaction authority is created only by a fresh purchase-context check in Shop.";
  return `
    <div class="guided-stage-kicker">STEP 5 · WHAT SHOULD HAPPEN NEXT?</div>
    <div class="guided-stage-number">05</div>
    <h2>${esc(heading)}</h2>
    <p class="guided-stage-lede">${esc(copy)}</p>
    <div class="guided-action-card ${blocked ? "blocked" : needsHuman ? "review" : "ready"}">
      <div class="guided-action-icon">${blocked ? "×" : needsHuman ? "H" : "→"}</div>
      <div><span>Policy-selected action</span><strong>${esc(result.selected_action.replaceAll("_", " "))}</strong><p>${esc(copy)}</p></div>
    </div>
    <div class="guided-action-chips">${(result.permitted_actions || []).map((action) => `<span>${esc(action.replaceAll("_", " "))}</span>`).join("")}</div>
    <p class="guided-measure-note">This is an exploratory guided receipt. It is auditable, but it is deliberately not purchase authority.</p>`;
}

function renderReceipt() {
  const receipt = result.receipt;
  const tone = resultTone(result.actor_decision);
  const totalChecks = receipt.check_results?.length || 0;
  const findings = receipt.reason_codes?.length || 0;
  return `
    <div class="guided-stage-kicker">STEP 6 · HUMAN SUMMARY + AUDIT RECEIPT</div>
    <div class="guided-stage-number">06</div>
    <h2>Finish with an answer a normal customer can understand.</h2>
    <p class="guided-stage-lede">The plain-language summary comes first. The signed JSON remains available for technical audit and verification.</p>
    <div class="guided-receipt-card">
      <div class="guided-receipt-head"><div class="guided-receipt-seal tone-${tone}">R</div><div><span>Human-friendly receipt</span><strong>${esc(result.traffic_light?.label || result.actor_decision)}</strong></div><b>${esc(receipt.receipt_id)}</b></div>
      <div class="guided-receipt-summary">
        <p><strong>What RAMIFY checked:</strong> product identity, seller, evidence, validity, claims, conflicts and recall/advisory status.</p>
        <p><strong>What RAMIFY found:</strong> ${esc(result.objective_light?.meaning || result.objective_posture.replaceAll("_", " "))}</p>
        <p><strong>Policy-selected next action:</strong> ${esc(result.selected_action.replaceAll("_", " "))} <em>(shown only in guided mode)</em></p>
      </div>
      <div class="guided-receipt-stats"><span><b>${totalChecks}</b> recorded checks</span><span><b>${findings}</b> finding${findings === 1 ? "" : "s"}</span><span><b>SHA-256 + Ed25519</b> integrity proof</span></div>
      <details><summary>View signed JSON receipt</summary><pre>${esc(JSON.stringify(receipt, null, 2))}</pre></details>
      <div class="guided-finish-row"><button class="btn btn-ghost" type="button" id="guided-verify-receipt">Verify signed receipt</button><button class="btn btn-ghost" type="button" id="guided-tamper-receipt">Verify tampered copy</button></div>
      <div class="terminal" id="guided-terminal" hidden></div>
    </div>
    <div class="guided-finish-row"><a class="btn" href="/shop?subject=${encodeURIComponent(result.subject_ref)}&actor=${encodeURIComponent(selectedScenario.actor_ref)}">Continue in the full shopping flow →</a><a class="btn btn-ghost" href="/technical">Open technical evidence</a></div>`;
}

function renderStage() {
  const renderers = [renderRequest, renderInterpretation, renderChecks, renderPolicies, renderNextAction, renderReceipt];
  const stage = $("guided-stage");
  stage.innerHTML = renderers[currentStep]();
  if (currentStep === 2) {
    $("guided-evidence-tamper")?.addEventListener("click", async () => {
      const terminal = $("guided-evidence-terminal");
      terminal.hidden = false;
      terminal.classList.remove("bad");
      terminal.textContent = "Running reversible synthetic evidence-tamper proof…";
      try {
        const proof = await api("/api/v0/demo/evidence-tamper", { subject_ref: result.subject_ref });
        terminal.classList.toggle("bad", proof.tampered_integrity?.state === "verified");
        terminal.textContent = [
          "$ RAMIFY evidence-integrity proof",
          "",
          `clean artefact       ${proof.clean_integrity?.state === "verified" ? "ok" : proof.clean_integrity?.state}`,
          `tampered artefact    ${proof.tampered_integrity?.state || "unknown"}`,
          `RATIFY check         ${proof.ratify_outcome || "unknown"}`,
          `objective posture    ${proof.objective_posture || "unknown"}`,
          `reason               ${(proof.reason_codes || []).join(", ") || "—"}`,
          `artefact restored    ${proof.artefact_restored ? "yes" : "NO"}`,
          "",
          proof.note || "",
        ].join("\n");
      } catch (error) {
        terminal.classList.add("bad");
        terminal.textContent = `Evidence-tamper proof failed to run: ${error.message}`;
      }
    });
  }
  if (currentStep === 5) {
    $("guided-verify-receipt")?.addEventListener("click", async () => {
      await verifyInto("guided-terminal", result.receipt, false);
      $("guided-terminal")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    $("guided-tamper-receipt")?.addEventListener("click", async () => {
      const tampered = JSON.parse(JSON.stringify(result.receipt));
      if (tampered.order && Number.isInteger(tampered.order.unit_price_cents)) tampered.order.unit_price_cents += 1;
      else tampered.product_name = `${tampered.product_name} [tampered copy]`;
      await verifyInto("guided-terminal", tampered, true);
      $("guided-terminal")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }
  stage.dataset.step = String(currentStep + 1);
  stage.classList.remove("guided-stage-enter");
  requestAnimationFrame(() => stage.classList.add("guided-stage-enter"));
  animateStageContents(stage);
}

function animateStageContents(stage) {
  if (!("animate" in stage) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const items = stage.querySelectorAll(":scope > *, .guided-field-grid > span, .guided-policy-grid > article, .guided-trace > div");
  items.forEach((node, index) => {
    node.animate(
      [{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 360, delay: Math.min(index, 10) * 34, easing: "cubic-bezier(.22,.8,.24,1)", fill: "both" }
    );
  });
}

function render() {
  renderRail();
  renderStage();

  $("guided-position").textContent = `Step ${currentStep + 1} of ${GUIDED_STEPS.length}`;
  const next = GUIDED_STEPS[currentStep + 1];
  $("guided-next-copy").textContent = next ? `Next: ${next[0]}` : "Walkthrough complete";
  $("guided-progress-bar").style.width = `${((currentStep + 1) / GUIDED_STEPS.length) * 100}%`;
  $("guided-progress-title").textContent = GUIDED_STEPS[currentStep][0];
  $("guided-progress-meta").textContent = `${currentStep + 1} / ${GUIDED_STEPS.length}`;
  $("guided-back").disabled = currentStep === 0;
  $("guided-next").hidden = currentStep === GUIDED_STEPS.length - 1;

  const ref = $("guided-receipt-ref");
  if (result?.receipt?.receipt_id) {
    ref.hidden = false;
    ref.innerHTML = `<span>Current receipt</span><code>${esc(result.receipt.receipt_id)}</code>`;
  }
}

function go(step, options = {}) {
  const nextStep = Math.max(0, Math.min(GUIDED_STEPS.length - 1, step));
  if (nextStep === currentStep) return;
  const stage = $("guided-stage");
  const renderNext = () => {
    currentStep = nextStep;
    render();
    if (options.scroll !== false) $("walkthrough").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  if (stage?.animate && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const direction = nextStep > currentStep ? -1 : 1;
    const exit = stage.animate(
      [{ opacity: 1, transform: "translateX(0) scale(1)" }, { opacity: 0, transform: `translateX(${direction * 18}px) scale(.992)` }],
      { duration: 150, easing: "ease", fill: "forwards" }
    );
    exit.addEventListener("finish", renderNext, { once: true });
  } else renderNext();
}

startPage(boot);

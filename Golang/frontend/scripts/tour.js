"use strict";

const SHIPPED_PERSONA_REFS = Object.freeze(["consumer_v1", "autonomous_buyer_v1", "budget_guard_v1", "brand_loyal_v1", "procurement_v1"]);

const GUIDED_PRODUCT_REF = "ramify:demo:supp:apex-mg-glyc-120";

const TOUR_STEPS = Object.freeze([
  {
    key: "product",
    short: "Product",
    sub: "Choose",
    kicker: "01 · PRODUCT",
    title: "Meet the product",
    intro: "Start with one real catalogue record from the demo dataset. Nothing has been trusted or authorised yet.",
  },
  {
    key: "request",
    short: "Request",
    sub: "Understand",
    kicker: "02 · REQUEST",
    title: "Understand what the shopper means",
    intro: "The guided walkthrough uses the fast deterministic matcher because the product is already known. Free-form Shop requests can use the native Go + Ollama Llama 3.1 adapter.",
  },
  {
    key: "ramify",
    short: "RAMIFY",
    sub: "Check",
    kicker: "03 · RAMIFY",
    title: "Check the product facts",
    intro: "RAMIFY now runs the authoritative deterministic checks. This is where the objective product result is created.",
  },
  {
    key: "agent",
    short: "Agent",
    sub: "Respond",
    kicker: "04 · AGENT",
    title: "Apply the delegated buying policy",
    intro: "Every agent sees the same objective product result. Their own policy can only change the permitted next action.",
  },
  {
    key: "receipt",
    short: "Receipt",
    sub: "Verify",
    kicker: "05 · RECEIPT",
    title: "Read and verify the decision receipt",
    intro: "The human summary explains the decision, while the signed JSON preserves the exact machine-readable record for audit.",
  },
  {
    key: "finish",
    short: "Checkout",
    sub: "Finish",
    kicker: "06 · CHECKOUT",
    title: "See the protected checkout boundary",
    intro: "The guided tour stops at the boundary on purpose. A real basket action requires a fresh purchase-context receipt created from Shop → Amplify.",
  },
]);

const tourState = {
  catalogue: null,
  product: null,
  step: 0,
  interpretation: null,
  assessment: null,
  comparison: null,
  verification: null,
  busy: false,
  error: "",
};

function guidedRequest() {
  const p = tourState.product;
  return `Please check ${p.name} from ${p.seller_name} before I buy it.`;
}

function timingMs(us) {
  return `${(Number(us || 0) / 1000).toFixed(3)} ms`;
}

function actionLabel() {
  const s = tourState.step;
  if (tourState.busy) {
    if (s === 1) return "Understanding request…";
    if (s === 2) return "Running checks…";
    if (s === 4) return "Verifying receipt…";
    return "Working…";
  }
  if (s === 0) return "Use this product";
  if (s === 1) return tourState.interpretation ? "Continue to RAMIFY" : "Understand request";
  if (s === 2) return tourState.assessment ? "Continue to agent" : "Run RAMIFY checks";
  if (s === 3) return "Continue to receipt";
  if (s === 4) return tourState.verification ? "Continue to checkout" : "Verify receipt";
  return "Finish tour & open Shop";
}

function actionHelper() {
  const s = tourState.step;
  if (tourState.busy) return "This local step is running now.";
  if (s === 0) return "This chooses the walkthrough product only. It does not start a purchase.";
  if (s === 1) return "Guided mode does not wait for Llama; the selected catalogue product is already known.";
  if (s === 2) return "Seven deterministic checks create the objective result before any agent policy is applied.";
  if (s === 3) return "Notice that the objective result stays the same across all five personas.";
  if (s === 4) return "Verification checks the signed receipt; it does not re-decide the product.";
  return "The real Shop is where you can deliberately start an Amplify purchase journey.";
}

function productImageMarkup(extraClass = "") {
  const p = tourState.product;
  const image = productImage(p.subject_ref);
  return `<div class="walkthrough-product-image ${extraClass}">
    <img src="${esc(image)}" alt="${esc(p.name)}">
  </div>`;
}

function renderProductStrip() {
  const p = tourState.product;
  $("walkthrough-product-strip").innerHTML = `
    ${productImageMarkup("compact")}
    <div class="walkthrough-product-strip-copy">
      <span>GUIDED PRODUCT</span>
      <strong>${esc(p.name)}</strong>
      <small>${esc(p.brand)} · ${esc(p.seller_name)} · ${esc(p.category)}</small>
    </div>
    <div class="walkthrough-product-price"><span>Demo price</span><strong>${money(p.price_cents)}</strong></div>
    <div class="walkthrough-product-ref"><span>Catalogue ID</span><code>${esc(p.subject_ref.split(":").pop())}</code></div>`;
}

function renderRail() {
  const step = TOUR_STEPS[tourState.step];
  $("walkthrough-count").textContent = `Step ${tourState.step + 1} of ${TOUR_STEPS.length}`;
  $("walkthrough-progress-label").textContent = step.short;
  $("walkthrough-progress").style.width = `${((tourState.step + 1) / TOUR_STEPS.length) * 100}%`;
  $("walkthrough-steps").innerHTML = TOUR_STEPS.map((item, index) => {
    const state = index < tourState.step ? "done" : index === tourState.step ? "active" : "upcoming";
    return `<div class="walkthrough-step ${state}" aria-current="${state === "active" ? "step" : "false"}">
      <span class="walkthrough-step-index">${index < tourState.step ? "✓" : index + 1}</span>
      <div><strong>${esc(item.short)}</strong><small>${esc(item.sub)}</small></div>
    </div>`;
  }).join("");
}

function renderStageHeader() {
  const step = TOUR_STEPS[tourState.step];
  $("walkthrough-kicker").textContent = step.kicker;
  $("walkthrough-stage-title").textContent = step.title;
  $("walkthrough-stage-intro").textContent = step.intro;
  $("walkthrough-stage-number").textContent = String(tourState.step + 1).padStart(2, "0");
}

function interpretationSummary() {
  if (!tourState.interpretation) return "";
  const x = tourState.interpretation;
  return `<div class="walkthrough-success-summary">
    <span class="walkthrough-success-icon">✓</span>
    <div><strong>Request matched to the selected catalogue product</strong>
      <small>${esc(agentSourceLabel(x.source))} · ${Number(x.latency_ms || 0).toFixed(3)} ms</small>
    </div>
  </div>`;
}

function checkRows() {
  const rows = tourState.assessment?.receipt?.check_results || [];
  return rows.map((check) => `
    <div class="walkthrough-check-row ${check.outcome === "pass" ? "pass" : "attention"}">
      <span class="walkthrough-check-state">${check.outcome === "pass" ? "✓" : "!"}</span>
      <div><strong>${esc(check.label)}</strong><small>${esc(check.detail)}</small></div>
      <span class="walkthrough-check-outcome">${esc(check.outcome)}</span>
    </div>`).join("");
}

function timingPanel() {
  const a = tourState.assessment;
  if (!a) return "";
  const trace = a.call_trace || [];
  const totalUs = a.receipt?.latencies_us?.total || trace.reduce((sum, row) => sum + Number(row.latency_us || 0), 0);
  return `<div class="walkthrough-timing-panel">
    <div class="walkthrough-timing-total"><span>Deterministic RAMIFY time</span><strong>${timingMs(totalUs)}</strong></div>
    <div class="walkthrough-timing-grid">
      ${trace.map((row) => `<div><span>${esc(row.primitive)}</span><strong>${timingMs(row.latency_us)}</strong></div>`).join("")}
    </div>
    <small>Measured on this local run; displayed separately from any LLM interpretation latency.</small>
  </div>`;
}

function renderProductStep() {
  const p = tourState.product;
  return `<div class="walkthrough-product-focus">
    ${productImageMarkup("hero")}
    <div class="walkthrough-product-details">
      <span class="walkthrough-pill neutral">Catalogue product</span>
      <h3>${esc(p.name)}</h3>
      <p>This is the exact product the walkthrough will follow. It is already present in RAMIFY's local catalogue, so no model needs to guess which item you selected.</p>
      <dl class="walkthrough-facts">
        <div><dt>Brand</dt><dd>${esc(p.brand)}</dd></div>
        <div><dt>Seller</dt><dd>${esc(p.seller_name)}</dd></div>
        <div><dt>Category</dt><dd>${esc(p.category)}</dd></div>
        <div><dt>Price</dt><dd>${money(p.price_cents)}</dd></div>
      </dl>
      <div class="walkthrough-boundary"><strong>Nothing is authorised yet.</strong><span>Selecting this demo product only establishes what the walkthrough is about.</span></div>
    </div>
  </div>`;
}

function renderRequestStep() {
  const p = tourState.product;
  return `<div class="walkthrough-request-layout">
    <div class="walkthrough-request-card">
      <div class="walkthrough-card-label">SHOPPER REQUEST</div>
      <blockquote>${esc(guidedRequest())}</blockquote>
      <div class="walkthrough-request-product">
        ${productImageMarkup("mini")}
        <div><strong>${esc(p.name)}</strong><small>${esc(p.seller_name)}</small></div>
      </div>
    </div>
    <div class="walkthrough-explain-card">
      <span class="walkthrough-pill ai">FAST GUIDED MODE</span>
      <h3>Known selection → deterministic match</h3>
      <p>Because this product was deliberately selected in the previous step, the guided tour does not send it to Llama just to identify it again.</p>
      <div class="walkthrough-flow-mini"><span>Selected product</span><b>→</b><span>Catalogue matcher</span><b>→</b><span>Product reference</span></div>
      <p class="walkthrough-caption">In the live Shop, genuinely free-form text can still use the native Go + Ollama + Llama 3.1 path.</p>
    </div>
    ${interpretationSummary()}
  </div>`;
}

function renderRamifyStep() {
  if (!tourState.assessment) {
    return `<div class="walkthrough-engine-ready">
      ${interpretationSummary()}
      <div class="walkthrough-engine-mark">R</div>
      <div><span class="walkthrough-pill neutral">AUTHORITATIVE CHECK</span>
        <h3>RAMIFY is ready to assess the product</h3>
        <p>The next action runs identity, standing, seller, evidence, validity, claims and conflict checks. No LLM decides these results.</p>
      </div>
      <div class="walkthrough-check-preview">${["Identity", "Standing", "Seller", "Evidence", "Freshness", "Claims", "Conflicts"].map((x) => `<span>${x}</span>`).join("")}</div>
    </div>`;
  }
  const a = tourState.assessment;
  return `<div class="walkthrough-result-layout">
    <div class="walkthrough-objective-card tone-${esc(a.objective_light.colour)}">
      <span>OBJECTIVE PRODUCT RESULT</span>
      <div class="walkthrough-light"><i></i><strong>${esc(a.objective_light.label)}</strong></div>
      <p>${esc(a.objective_light.meaning)}</p>
      <small>${esc(a.objective_posture.replaceAll("_", " "))}</small>
    </div>
    ${timingPanel()}
    <div class="walkthrough-check-list">${checkRows()}</div>
  </div>`;
}

function renderAgentStep() {
  const a = tourState.assessment;
  const personas = tourState.comparison?.personas || [];
  return `<div class="walkthrough-agent-layout">
    <div class="walkthrough-lock-banner">
      <div><span>OBJECTIVE RESULT IS LOCKED</span><strong>${esc(a.objective_light.label)}</strong></div>
      <p>Each persona receives the same product facts. Only delegated policy changes the permitted next action.</p>
    </div>
    <div class="walkthrough-personas">
      ${personas.map((x) => `<article class="walkthrough-persona ${personaClass(x.actor_ref)} ${x.actor_ref === a.actor_ref ? "selected" : ""}">
        <div class="walkthrough-persona-top"><span class="walkthrough-persona-avatar">${esc(x.actor_label.slice(0,1))}</span><span>${x.actor_ref === a.actor_ref ? "Selected" : "Comparison"}</span></div>
        <h3>${esc(x.actor_label)}</h3>
        <div class="walkthrough-persona-decision">${esc(x.decision.replaceAll("_", " "))}</div>
        <small>${esc((x.selected_action || "halt").replaceAll("_", " "))}</small>
      </article>`).join("")}
    </div>
    <div class="walkthrough-decision-split">
      <div><span>Objective trust</span><strong>${esc(a.objective_light.label)}</strong><small>Created by deterministic product checks</small></div>
      <div><span>Consumer agent decision</span><strong>${esc(a.traffic_light.label)}</strong><small>${esc(a.selected_action_description || a.selected_action)}</small></div>
    </div>
  </div>`;
}

function receiptFindings() {
  const checks = tourState.assessment?.receipt?.check_results || [];
  const attention = checks.filter((x) => x.outcome !== "pass");
  if (!attention.length) return "All seven product checks passed for this catalogue record.";
  return attention.map((x) => `${x.label}: ${x.detail}`).join(" ");
}

function renderReceiptStep() {
  const a = tourState.assessment;
  const r = a.receipt;
  const verified = Boolean(tourState.verification?.verified);
  return `<div class="walkthrough-receipt-layout">
    <article class="walkthrough-human-receipt ${verified ? "verified" : ""}">
      <header><div><span>HUMAN-FRIENDLY RECEIPT</span><h3>${esc(a.product_name)}</h3></div><div class="walkthrough-receipt-seal">${verified ? "✓" : "R"}</div></header>
      <div class="walkthrough-receipt-summary">
        <div><span>Product result</span><strong>${esc(a.objective_light.label)}</strong></div>
        <div><span>Consumer agent</span><strong>${esc(a.traffic_light.label)}</strong></div>
        <div><span>Permitted next action</span><strong>${esc((a.selected_action || "halt").replaceAll("_", " "))}</strong></div>
      </div>
      <p><strong>What RAMIFY found:</strong> ${esc(receiptFindings())}</p>
      <p><strong>Receipt ID:</strong> <code>${esc(r.receipt_id)}</code></p>
      <div class="walkthrough-verify-banner ${verified ? "ok" : "pending"}">
        <span>${verified ? "✓" : "…"}</span><div><strong>${verified ? "Signed receipt verified" : "Verification not run yet"}</strong><small>${verified ? "The signed payload is intact for this local demo record." : "Use the button below to verify the receipt before continuing."}</small></div>
      </div>
    </article>
    <details class="walkthrough-json">
      <summary>View the machine-readable receipt</summary>
      <pre>${esc(JSON.stringify({
        receipt_id: r.receipt_id,
        subject_ref: r.subject_ref,
        assessment_context: r.assessment_context,
        objective_posture: r.objective_posture,
        actor_decision: r.actor_decision,
        selected_action: r.selected_action,
        payload_hash: r.payload_hash,
        signature: r.signature,
      }, null, 2))}</pre>
    </details>
  </div>`;
}

function renderFinishStep() {
  const a = tourState.assessment;
  const verified = Boolean(tourState.verification?.verified);
  return `<div class="walkthrough-finish-layout">
    <div class="walkthrough-finish-hero">
      <span class="walkthrough-finish-check">✓</span>
      <div><span class="walkthrough-pill success">GUIDED JOURNEY COMPLETE</span>
        <h3>The product is eligible for the consumer agent's next action.</h3>
        <p>RAMIFY produced an <strong>${esc(a.objective_light.label)}</strong> product result and the Consumer shopping agent selected <strong>${esc((a.selected_action || "halt").replaceAll("_", " "))}</strong>.</p>
      </div>
    </div>
    <div class="walkthrough-checkout-boundary">
      <div class="walkthrough-boundary-icon">↗</div>
      <div><span>IMPORTANT CHECKOUT BOUNDARY</span><h3>The guided tour does not create purchase authority.</h3>
        <p>This walkthrough used an <code>interactive_tour</code> receipt so it cannot silently add anything to the real demo basket. To create basket authority, deliberately open Shop, choose the product and start the <strong>Amplify</strong> purchase journey.</p>
      </div>
    </div>
    <div class="walkthrough-finish-grid">
      <div><span>Product</span><strong>${esc(a.product_name)}</strong></div>
      <div><span>Receipt</span><strong>${verified ? "Verified" : "Not verified"}</strong></div>
      <div><span>Tour side effects</span><strong>None</strong></div>
      <div><span>Next</span><strong>Open the real Shop</strong></div>
    </div>
  </div>`;
}

function renderStageBody() {
  const s = tourState.step;
  let html = "";
  if (s === 0) html = renderProductStep();
  else if (s === 1) html = renderRequestStep();
  else if (s === 2) html = renderRamifyStep();
  else if (s === 3) html = renderAgentStep();
  else if (s === 4) html = renderReceiptStep();
  else html = renderFinishStep();
  $("walkthrough-stage-body").innerHTML = html;
}

function renderActions() {
  const back = $("walkthrough-back");
  back.disabled = tourState.step === 0 || tourState.busy;
  $("walkthrough-primary").disabled = tourState.busy;
  $("walkthrough-primary").classList.toggle("is-busy", tourState.busy);
  $("walkthrough-primary-label").textContent = actionLabel();
  $("walkthrough-action-copy").textContent = actionHelper();
}

function renderError() {
  const box = $("walkthrough-error");
  box.hidden = !tourState.error;
  box.innerHTML = tourState.error ? `<strong>This step did not complete.</strong><span>${esc(tourState.error)}</span><small>Nothing was authorised. You can safely try the step again.</small>` : "";
}

function animateStage() {
  const stage = $("walkthrough-stage-body");
  if (!stage?.animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  stage.animate(
    [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
    { duration: 260, easing: "cubic-bezier(.2,.8,.25,1)" }
  );
}

function renderTour({ animate = false } = {}) {
  renderRail();
  renderStageHeader();
  renderStageBody();
  renderActions();
  renderError();
  if (animate) animateStage();
}

function goToStep(next) {
  tourState.step = Math.max(0, Math.min(TOUR_STEPS.length - 1, next));
  tourState.error = "";
  renderTour({ animate: true });
  $("walkthrough-stage").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runPrimaryAction() {
  if (tourState.busy) return;
  tourState.error = "";
  try {
    if (tourState.step === 0) {
      goToStep(1);
      return;
    }

    if (tourState.step === 1) {
      if (!tourState.interpretation) {
        tourState.busy = true;
        renderTour();
        tourState.interpretation = await api("/api/v0/interpret", {
          request_text: guidedRequest(),
          actor_ref: "consumer_v1",
          mode: "deterministic",
          candidate_refs: [tourState.product.subject_ref],
        });
      }
      goToStep(2);
      return;
    }

    if (tourState.step === 2) {
      if (!tourState.assessment) {
        tourState.busy = true;
        renderTour();
        const identifier = tourState.interpretation?.identifier || tourState.product.subject_ref;
        const [assessment, comparison] = await Promise.all([
          api("/api/v0/assess", {
            identifier,
            actor_ref: "consumer_v1",
            quantity: 1,
            context: "interactive_tour",
          }),
          api("/api/v0/compare", { identifier, quantity: 1, actor_refs: SHIPPED_PERSONA_REFS }),
        ]);
        tourState.assessment = assessment;
        tourState.comparison = comparison;
      }
      goToStep(3);
      return;
    }

    if (tourState.step === 3) {
      goToStep(4);
      return;
    }

    if (tourState.step === 4) {
      if (!tourState.verification) {
        tourState.busy = true;
        renderTour();
        tourState.verification = await api("/api/v0/receipt/verify", tourState.assessment.receipt);
        if (!tourState.verification?.verified) throw new Error("The guided receipt did not pass verification.");
      }
      goToStep(5);
      return;
    }

    sessionStorage.setItem("ramify-welcome-seen", "1");
    window.location.href = "/shop";
  } catch (error) {
    tourState.error = error?.message || "This guided step could not complete.";
    toast(tourState.error, "bad");
  } finally {
    tourState.busy = false;
    if (tourState.step < TOUR_STEPS.length) renderTour();
  }
}

function goBack() {
  if (tourState.busy || tourState.step === 0) return;
  goToStep(tourState.step - 1);
}

async function bootTour() {
  mountShell("/tour");
  document.body.classList.add("guided-focus");
  mountFooter();
  sessionStorage.setItem("ramify-welcome-seen", "1");

  tourState.catalogue = await catalogue();
  tourState.product = tourState.catalogue.products.find((p) => p.subject_ref === GUIDED_PRODUCT_REF);
  if (!tourState.product) throw new Error("The Apex Magnesium guided product is missing from the local catalogue.");

  renderProductStrip();
  renderTour();

  $("walkthrough-primary").addEventListener("click", runPrimaryAction);
  $("walkthrough-back").addEventListener("click", goBack);
  document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" && !tourState.busy && tourState.step > 0) goBack();
  });
}

startPage(bootTour);

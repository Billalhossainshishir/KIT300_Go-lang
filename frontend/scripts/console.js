"use strict";

// The shopping console.
//
// The order is deliberate: the light first because it is the answer, the
// working after for anyone who wants it. When the answer is not green the page
// changes state rather than just colour — a handover should look like one.

let current = null;
let shopCatalogue = null;
let selectedProductRef = null;
let selectedRequestText = "";
let journeyStep = 0;
let journeyMax = 0;

const OUTCOME_PILL = { pass: "pass", review: "review", fail: "fail", incomplete: "incomplete" };

const REQUIRED_SCENARIOS = Object.freeze([
  ["Approved", "APPROVED-001"],
  ["Expired evidence", "EXPIRED-001"],
  ["Seller risk", "SELLER-RISK-001"],
  ["Recall", "RECALL-001"],
  ["Substitution", "SUBSTITUTION-001"],
]);


// Derived from the result, not sniffed out of a string, so a recalled batch
// cannot come out green.
function traceTone(step, result) {
  const r = result.receipt;
  switch (step.primitive) {
    case "identify":
      return result.resolved
        ? { label: "found it", tone: "pass" }
        : { label: "no match", tone: "incomplete" };
    case "resolve":
      return {
        label: r.canonical_state === "asserted" ? "on record" : "nothing on record",
        tone: r.canonical_state === "asserted" ? "pass" : "incomplete",
      };
    case "status": {
      const s = r.status_result.standing;
      const label = { no_active_recall: "no recall", advisory: "advisory", recalled: "recalled" }[s] || s;
      return { label, tone: s === "no_active_recall" ? "pass" : s === "recalled" ? "fail" : "review" };
    }
    case "verify": {
      const findings = r.check_results.filter((c) => c.outcome !== "pass");
      if (!findings.length) return { label: "all seven passed", tone: "pass" };
      const tone = findings.some((c) => c.outcome === "fail")
        ? "fail"
        : findings.some((c) => c.outcome === "incomplete")
        ? "incomplete"
        : "review";
      return { label: `${findings.length} finding${findings.length > 1 ? "s" : ""}`, tone };
    }
    case "assess":
      return {
        label: result.objective_posture,
        tone: { green: "pass", orange: "review", red: "fail" }[result.objective_light.colour],
      };
    default:
      return { label: step.output, tone: "incomplete" };
  }
}

async function boot() {
  mountShell("/shop");
  mountFirstRunWelcome();
  shopCatalogue = await catalogue();
  mountFooter();

  $("actor").innerHTML = shopCatalogue.actor_profiles
    .map((p) => `<option value="${esc(p.ref)}">${esc(p.label)}</option>`)
    .join("");
  $("actor").addEventListener("change", async () => {
    await showProfileNote();
    if (current) {
      const keep = journeyStep;
      await run(current.request_text || current.subject_ref, { preserveStep: keep });
    }
  });
  showProfileNote();

  $("catalogue").innerHTML = shopCatalogue.products
    .map(
      (p) => `
      <div class="card" data-ref="${esc(p.subject_ref)}" tabindex="0" role="button"
           aria-label="Select ${esc(p.name)}">
        <div class="product-card-image">
          <img src="${esc(productImage(p.subject_ref))}" alt="${esc(p.name)}" loading="lazy">
        </div>
        <div class="name">${esc(p.name)}</div>
        <div class="meta">${esc(p.brand)}${p.batch_ref ? " · batch " + esc(p.batch_ref) : ""}</div>
        <div class="price">${money(p.price_cents)}</div>
        <div class="card-action">Select product <span>→</span></div>
        <button class="inspect" data-inspect="${esc(p.subject_ref)}">Trust passport</button>
      </div>`
    )
    .join("");

  renderScenarios(shopCatalogue);
  $("start-fresh").addEventListener("click", startFresh);
  $("open-cases").addEventListener("click", () => setDrawer(true));
  $("close-cases").addEventListener("click", () => setDrawer(false));
  $("case-scrim").addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (e) => e.key === "Escape" && setDrawer(false));

  $("catalogue").addEventListener("click", (event) => {
    const inspect = event.target.closest("[data-inspect]");
    if (inspect) {
      event.stopPropagation();
      return openTrustPassport(inspect.dataset.inspect, current);
    }
    const card = event.target.closest(".card");
    if (card) selectProduct(card.dataset.ref);
  });
  $("catalogue").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    // The Trust passport control is a real button nested inside the selectable
    // product card. Let the button own its keyboard activation instead of
    // turning Enter/Space into an accidental product selection.
    if (event.target.closest("[data-inspect]")) return;
    const card = event.target.closest(".card");
    if (card) {
      event.preventDefault();
      selectProduct(card.dataset.ref);
    }
  });

  $("run").addEventListener("click", () => run($("query").value.trim()));
  $("query").addEventListener("keydown", (e) => e.key === "Enter" && run($("query").value.trim()));
  $("query").addEventListener("input", handleRequestEdit);
  $("qty").addEventListener("change", () => current && run(current.request_text || current.subject_ref, { preserveStep: journeyStep }));
  $("continue-ramify").addEventListener("click", () => {
    const request = selectedRequestText || selectedProductRef;
    if (request) run(request);
  });
  $("journey-back").addEventListener("click", () => goJourney(Math.max(0, journeyStep - 1)));
  $("journey-next").addEventListener("click", () => goJourney(Math.min(5, journeyStep + 1)));

  $$('[data-journey-step]').forEach((button) => button.addEventListener('click', () => {
    const step = Number(button.dataset.journeyStep);
    if (step <= journeyMax) goJourney(step);
  }));

  const preset = new URLSearchParams(location.search);
  const presetActor = preset.get("actor");
  if (presetActor && shopCatalogue.actor_profiles.some((profile) => profile.ref === presetActor)) {
    $("actor").value = presetActor;
  }
  const presetSubject = preset.get("subject");
  if (presetSubject && shopCatalogue.products.some((product) => product.subject_ref === presetSubject)) {
    showProfileNote();
    selectProduct(presetSubject);
  }
  if (preset.get("guide") === "1") {
    sessionStorage.setItem("ramify-welcome-seen", "1");
  }
  goJourney(0);
}

function clearDecisionOutput() {
  current = null;
  const result = $("result");
  if (result) result.hidden = true;
  const terminal = $("terminal");
  if (terminal) { terminal.hidden = true; terminal.textContent = ""; terminal.classList.remove("bad"); }
  const banner = $("ai-fallback-banner");
  if (banner) banner.hidden = true;
  const evidence = $("evidence-trail-panel");
  if (evidence) { evidence.hidden = true; evidence.innerHTML = ""; }
  const alternatives = $("alternatives");
  if (alternatives) { alternatives.hidden = true; alternatives.innerHTML = ""; }
  const human = $("human");
  if (human) human.innerHTML = "";
  const actionLog = $("action-log");
  if (actionLog) actionLog.innerHTML = "";
}

function clearPreparedProduct({ keepQuery = false, preserveActor = true } = {}) {
  clearDecisionOutput();
  selectedProductRef = null;
  selectedRequestText = "";
  journeyStep = 0;
  journeyMax = 0;
  if (!keepQuery) $("query").value = "";
  $("selection-panel").hidden = true;
  $$(".card").forEach((card) => card.classList.remove("selected"));
  if (!preserveActor && shopCatalogue?.actor_profiles?.length) {
    const preferred = shopCatalogue.actor_profiles.find((p) => p.ref === "consumer_v1") || shopCatalogue.actor_profiles[0];
    $("actor").value = preferred.ref;
    showProfileNote();
  }
  goJourney(0);
}

function handleRequestEdit() {
  const value = $("query").value.trim();
  if (selectedProductRef && value !== selectedRequestText) {
    selectedProductRef = null;
    $("selection-panel").hidden = true;
    $$(".card").forEach((card) => card.classList.remove("selected"));
  }
  if (current && value !== String(current.request_text || "").trim()) {
    clearDecisionOutput();
    journeyStep = 0;
    journeyMax = 0;
    goJourney(0);
  }
}

function selectProduct(subjectRef) {
  const product = shopCatalogue?.products.find((p) => p.subject_ref === subjectRef);
  if (!product) return;
  if (current && current.subject_ref !== subjectRef) {
    clearDecisionOutput();
    journeyStep = 0;
    journeyMax = 0;
  }
  selectedProductRef = subjectRef;
  selectedRequestText = `Check ${product.name}${product.seller_name ? ` from ${product.seller_name}` : ""}.`;
  $("query").value = selectedRequestText;
  $$(".card").forEach((c) => c.classList.toggle("selected", c.dataset.ref === subjectRef));
  $("selection-name").textContent = product.name;
  $("selection-meta").textContent = `${product.brand}${product.batch_ref ? ` · batch ${product.batch_ref}` : ""} · ${money(product.price_cents)}`;
  const imageUrl = productImage(product.subject_ref);
  $("selection-icon").innerHTML = imageUrl
    ? `<img src="${esc(imageUrl)}" alt="" aria-hidden="true">`
    : "✓";
  $("selection-panel").hidden = false;
  $("selection-panel").classList.remove("selection-pop");
  requestAnimationFrame(() => $("selection-panel").classList.add("selection-pop"));
  $("selection-panel").scrollIntoView({ behavior: "smooth", block: "center" });
}

function goJourney(step) {
  journeyStep = Math.max(0, Math.min(5, Number(step) || 0));
  if (journeyStep > journeyMax) journeyMax = journeyStep;

  const shopHeader = document.querySelector(".shop-head");
  const productLine = document.querySelector(".ramify-product-line");
  const journeyPromise = document.querySelector(".journey-promise");
  const shopOnlyVisible = journeyStep === 0;
  if (shopHeader) shopHeader.hidden = !shopOnlyVisible;
  if (productLine) productLine.hidden = !shopOnlyVisible;
  if (journeyPromise) journeyPromise.hidden = !shopOnlyVisible;

  $(".journey-stage").forEach((stage) => {
    const active = Number(stage.dataset.stage) === journeyStep;
    stage.hidden = !active;
    stage.classList.toggle("active", active);
  });
  $$('[data-journey-step]').forEach((button) => {
    const value = Number(button.dataset.journeyStep);
    button.disabled = value > journeyMax;
    button.classList.toggle("active", value === journeyStep);
    button.classList.toggle("done", value < journeyStep && value <= journeyMax);
  });

  const nav = $("journey-nav");
  nav.hidden = journeyStep === 0 || !current;
  if (!nav.hidden) {
    $("journey-position").textContent = `Step ${journeyStep + 1} of 6`;
    const labels = ["", "Next: RAMIFY checks", "Next: Agent response", "Next: Receipt summary", "Next: Checkout", ""];
    $("journey-next-label").textContent = labels[journeyStep] || "Final step";
    $("journey-back").disabled = journeyStep <= 1;
    $("journey-next").hidden = journeyStep >= 5;
  }

  renderTrustTimeline();
  const stage = $(`journey-stage-${journeyStep}`);
  if (stage && journeyStep > 0) stage.scrollIntoView({ behavior: "smooth", block: "start" });
}

// The cases are an operator's tool, not shop furniture, so they live in a
// drawer. A buyer never has to see them; whoever is presenting reaches any of
// the seventeen in one click.
const SCENARIO_TITLE = {
  "APPROVED-001": "A clean result",
  "APPROVED-002": "The same product, under procurement",
  "ADVISORY-001": "A batch under advisory",
  "ADVISORY-EXPIRED-001": "Advisory and lapsed paperwork together",
  "EXPIRED-001": "A lapsed lab certificate",
  "EXPIRED-002": "The same lapse, for procurement",
  "PROOF-CONSUMER-001": "The proof case · consumer",
  "PROOF-PROCUREMENT-001": "The proof case · procurement",
  "CONFLICT-001": "Two sources disagree",
  "SUBSTITUTION-001": "Discontinued, with a replacement",
  "SUBSTITUTION-TARGET-001": "The replacement itself",
  "INCOMPLETE-001": "Nothing on file to judge",
  "RECALL-001": "An active recall",
  "RECALL-002": "The same recall, for procurement",
  "SELLER-RISK-001": "A seller not established",
  "SELLER-RISK-002": "The same seller, for procurement",
  "REVOKED-CERT-001": "A withdrawn certificate",
};

const LIGHT_OF_POSTURE = {
  allow: "green",
  allow_with_warning: "orange",
  hold: "orange",
  escalate: "orange",
  block: "red",
};

function scenarioStoryMeta(scenario) {
  const featured = {
    "APPROVED-001": ["Everything checks out", "A clean path from product evidence to a permitted action.", "Clean path"],
    "EXPIRED-001": ["Evidence needs attention", "The product is known, but one evidence record is no longer current.", "Evidence"],
    "SELLER-RISK-001": ["The seller changes the answer", "The product can be known while the seller still needs scrutiny.", "Seller"],
    "RECALL-001": ["A recall stops the journey", "A hard product-trust stop that no agent persona can make more permissive.", "Recall"],
    "SUBSTITUTION-001": ["The product has changed", "RAMIFY keeps the original decision separate and points to a replacement for reassessment.", "Replacement"],
  };
  const fallbackTitle = SCENARIO_TITLE[scenario.id] || scenario.id;
  const [title, description, category] = featured[scenario.id] || [fallbackTitle, scenario.note, scenarioCategory(scenario)];
  return { title, description, category };
}

function scenarioCategory(scenario) {
  const id = String(scenario.id || "");
  if (id.includes("RECALL")) return "Recall";
  if (id.includes("SELLER")) return "Seller";
  if (id.includes("EXPIRED") || id.includes("PROOF") || id.includes("REVOKED") || id.includes("INCOMPLETE")) return "Evidence";
  if (id.includes("SUBSTITUTION")) return "Replacement";
  if (id.includes("CONFLICT")) return "Conflict";
  if (id.includes("ADVISORY")) return "Advisory";
  return "Clean path";
}

function scenarioToneLabel(tone) {
  return tone === "red" ? "Block" : tone === "orange" ? "Needs attention" : "Allow";
}

function scenarioCard(scenario, cat, featured = false) {
  const tone = LIGHT_OF_POSTURE[scenario.expected_decision] || "orange";
  const meta = scenarioStoryMeta(scenario);
  const product = cat.products.find((p) => p.subject_ref === scenario.subject_ref);
  const actor = cat.actor_profiles.find((a) => a.ref === scenario.actor_ref);
  return `<button class="scenario story-card ${featured ? "featured" : ""} tone-${esc(tone)}" data-story-tone="${esc(tone)}" data-scenario="${esc(scenario.id)}"
      data-subject="${esc(scenario.subject_ref)}" data-actor="${esc(scenario.actor_ref)}">
    <span class="story-card-top"><span class="story-category">${esc(meta.category)}</span><span class="story-outcome ${esc(tone)}"><i></i>${esc(scenarioToneLabel(tone))}</span></span>
    <span class="story-card-copy"><strong>${esc(meta.title)}</strong><small>${esc(meta.description || scenario.note)}</small></span>
    <span class="story-card-context"><span>${esc(product?.name || scenario.subject_ref)}</span><span>${esc(actor?.label || scenario.actor_ref)}</span></span>
    <span class="story-card-action">Prepare this story <b aria-hidden="true">→</b></span>
  </button>`;
}

function chooseScenario(button) {
  const actor = $("actor");
  if (actor) actor.value = button.dataset.actor;
  showProfileNote();
  selectProduct(button.dataset.subject);
  setDrawer(false);
  const title = button.querySelector(".story-card-copy strong")?.textContent || "Demo story";
  toast(`${title} prepared. RAMIFY will wait until you continue.`, "good");
}

function renderScenarios(cat) {
  const featuredSlot = $("scenario-featured");
  const allSlot = $("scenarios");
  if (!allSlot) return;

  const featuredScenarios = REQUIRED_SCENARIOS
    .map(([, id]) => cat.scenarios.find((scenario) => scenario.id === id))
    .filter(Boolean);

  if (featuredSlot) {
    featuredSlot.innerHTML = featuredScenarios.map((scenario) => scenarioCard(scenario, cat, true)).join("");
  }

  allSlot.innerHTML = cat.scenarios.map((scenario) => scenarioCard(scenario, cat, false)).join("");
  const count = $("story-library-count");
  if (count) count.textContent = `${cat.scenarios.length} cases`;

  $$('[data-scenario]', $("case-drawer")).forEach((button) => button.addEventListener("click", () => chooseScenario(button)));

  const filterBar = $("story-filter-bar");
  if (filterBar) {
    $$('[data-story-filter]', filterBar).forEach((filter) => filter.addEventListener("click", () => {
      const wanted = filter.dataset.storyFilter;
      $$('[data-story-filter]', filterBar).forEach((item) => item.classList.toggle("active", item === filter));
      $$(".story-all-grid .story-card").forEach((card) => {
        card.hidden = wanted !== "all" && card.dataset.storyTone !== wanted;
      });
    }));
  }
}

function setDrawer(open) {
  const drawer = $("case-drawer");
  const scrim = $("case-scrim");
  if (!drawer || (open && !drawer.hidden) || (!open && drawer.hidden)) return;

  if (open) {
    scrim.hidden = false;
    drawer.hidden = false;
    // One frame between unhiding and adding the class, or the transition has
    // nothing to run from.
    requestAnimationFrame(() => {
      scrim.classList.add("shown");
      drawer.classList.add("shown");
    });
    $("close-cases").focus();
  } else {
    scrim.classList.remove("shown");
    drawer.classList.remove("shown");
    setTimeout(() => {
      scrim.hidden = true;
      drawer.hidden = true;
    }, 340);
    $("open-cases").focus();
  }
  $("open-cases").setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("drawer-open", open);
}

async function showProfileNote() {
  const cat = await catalogue();
  const p = cat.actor_profiles.find((x) => x.ref === $("actor").value);
  const note = $("profile-note");
  note.textContent = p ? p.description : "";
  note.className = `action-note persona-profile-note ${personaClass(p?.ref)}`;
}

async function run(requestText, options = {}) {
  if (!requestText) return;
  const originalRequest = String(requestText).trim();
  // Constrain the LLM only when this run came from the product the shopper
  // explicitly selected. A newly typed request must be free to match another
  // catalogue item instead of inheriting a stale card selection.
  const candidateRefs =
    originalRequest === selectedRequestText && selectedProductRef ? [selectedProductRef] : null;
  selectedRequestText = originalRequest;
  $("terminal").hidden = true;
  const alternativesSlot = $("alternatives");
  if (alternativesSlot) {
    alternativesSlot.hidden = true;
    alternativesSlot.innerHTML = "";
  }
  $("run").disabled = true;
  $("continue-ramify").disabled = true;
  $("run").textContent = "Understanding…";
  $("continue-ramify").textContent = "Checking…";

  try {
    const interpretationMode = candidateRefs?.length === 1 ? "deterministic" : "auto";
    const reading = await api("/api/v0/interpret", {
      request_text: originalRequest,
      actor_ref: $("actor").value,
      mode: interpretationMode,
      candidate_refs: candidateRefs,
    });
    renderInterpretation(reading, originalRequest);
    if (!reading.identifier) {
      clearPreparedProduct({ keepQuery: true, preserveActor: true });
      $("query").value = originalRequest;
      toast("I could not match that request to a product in this local catalogue. No previous product remains selected.", "bad");
      return;
    }

    const identifier = reading.identifier;
    selectedProductRef = identifier;
    $("query").value = originalRequest;
    $$(".card").forEach((c) => c.classList.toggle("selected", c.dataset.ref === identifier));
    $("run").textContent = "Checking…";

    const result = await api("/api/v0/assess", {
      identifier,
      actor_ref: $("actor").value,
      quantity: Number($("qty").value) || 1,
      context: "purchase",
    });
    result.interpretation = reading;
    result.request_text = originalRequest;
    current = result;

    $("result").hidden = false;
    renderVerdict(result);
    renderBuyStrip(result);
    renderTrace(result);
    renderConditions(result);
    renderGate(result);
    renderReceipt(result);
    renderExplanation(result.receipt);
    renderActionLog();
    void renderAlternatives(result);
    renderCheckoutState(result);
    renderTrustTimeline();
    renderSessionSummary(result);
    refreshBadges();

    if (options.preserveStep == null) journeyMax = 1;
    goJourney(options.preserveStep != null ? options.preserveStep : 1);
  } catch (error) {
    toast(error.message, "bad");
  } finally {
    $("run").disabled = false;
    $("continue-ramify").disabled = false;
    $("run").textContent = "Use this request";
    $("continue-ramify").textContent = "Continue with RAMIFY →";
  }
}

function renderCheckoutState(result) {
  const blocked = $("checkout-blocked");
  const title = $("checkout-stage-title");
  const copy = $("checkout-stage-copy");
  if (result.can_add_to_cart || result.can_create_requisition) {
    blocked.hidden = true;
    if (result.can_create_requisition && !result.can_add_to_cart) {
      title.textContent = "The checked product can move to a requisition";
      copy.textContent = "This agent uses a procurement workflow. The signed product decision can create a simulated requisition, not a consumer basket line.";
    } else {
      title.textContent = "The checked product can move to checkout";
      copy.textContent = "The recorded decision permits this simulated purchase. The receipt will travel with the basket line.";
    }
    return;
  }

  $("buy-strip").hidden = true;
  blocked.hidden = false;
  const needsHuman = result.requires_human || ["hold", "escalate"].includes(result.actor_decision);
  const hardStop = result.objective_posture === "block" || result.actor_decision === "block";
  if (hardStop) {
    title.textContent = "Checkout is blocked for this product";
    copy.textContent = "A hard-stop finding cannot be overridden. Choose another product or review a trusted alternative.";
    blocked.innerHTML = `<div class="checkout-state-icon red">×</div><div><h3>This item cannot be checked out</h3><p>The receipt records a block. RAMIFY keeps that decision attached to the product instead of allowing it into the basket.</p></div><button class="btn btn-ghost" id="checkout-restart">Choose another product</button>`;
  } else if (needsHuman) {
    title.textContent = "A person needs to decide before checkout";
    copy.textContent = "Your agent paused. The original product result remains unchanged while a human decision is recorded separately.";
    blocked.innerHTML = `<div class="checkout-state-icon amber">!</div><div><h3>Human review required</h3><p>Open Needs me to approve, decline or request an alternative. A linked human receipt will record that decision.</p></div><a class="btn" href="/review">Open human review →</a>`;
  } else {
    title.textContent = "This result does not permit checkout";
    copy.textContent = "Choose a permitted next action or another product.";
    blocked.innerHTML = `<div class="checkout-state-icon">→</div><div><h3>No purchase action is available</h3><p>The recorded decision controls what can happen next.</p></div><button class="btn btn-ghost" id="checkout-restart">Choose another product</button>`;
  }
  const restart = $("checkout-restart");
  if (restart) restart.onclick = () => {
    clearPreparedProduct({ keepQuery: false, preserveActor: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
    toast("Choose another product. Existing receipts and audit history were not changed.", "good");
  };
}

function renderInterpretation(reading, requestText) {
  const node = $("interpretation");
  node.hidden = false;
  const confidence = Math.round((reading.confidence || 0) * 100);
  const strength = confidence >= 90 ? "High" : confidence >= 70 ? "Medium" : "Low";
  const source = agentSourceLabel(reading.source);
  const aiUsed = String(reading.source || "").startsWith("langgraph+") || String(reading.source || "").includes("ollama");
  const direct = ["selected_catalogue_item", "exact_identifier"].includes(reading.source);
  const fallback = reading.source === "deterministic_fallback";
  const matcher = reading.source === "deterministic_catalogue_search";
  const aiTiming = Number.isFinite(Number(reading.latency_ms))
    ? `<span class="interpret-time">${Number(reading.latency_ms).toFixed(3)} ms</span>`
    : "";
  const icon = aiUsed ? "AI" : direct ? "✓" : "↳";
  const heading = aiUsed ? "Understood with local AI" : direct ? "Matched directly from the catalogue" : "Matched with the safe catalogue matcher";
  node.innerHTML = `
    <div class="interpret-icon ${aiUsed ? "is-ai" : "is-match"}">${icon}</div>
    <div>
      <strong>${esc(heading)}:</strong> ${esc(reading.note)}
      <div class="interpret-meta">${esc(source)} · ${strength} match strength · interpretation only ${aiTiming}</div>
    </div>
    <div class="interpret-boundary">This step identifies a known product only. Product trust is created by the deterministic RAMIFY checks in the next step.</div>`;
  const banner = $("ai-fallback-banner");
  banner.hidden = !fallback;
  if (fallback) {
    banner.innerHTML = `<span class="fallback-orb" aria-hidden="true"></span><div><strong>Local AI was unavailable or too slow</strong><p>RAMIFY used its safe catalogue matcher instead. The authoritative trust decision remains deterministic.</p></div>`;
  }
  if (matcher && !fallback) banner.hidden = true;
}

function renderVerdict(result) {
  const priced = result.order && result.order.line_total_cents != null;
  const aside = priced
    ? `<div class="sum">${esc(result.order.quantity)} × ${money(result.order.unit_price_cents)}
       = <strong>${money(result.order.line_total_cents)}</strong></div>`
    : "";

  $("verdict").innerHTML =
    renderLight(result.traffic_light, result.actor_decision, aside) +
    renderVerdictSplit(result) +
    renderEscalation(result.escalation, result.actor_label);
  renderRiskPath(result);
  renderWhyPanel(result);
}

// "You may proceed" with nothing to press is not an ending. This is where a
// good result becomes a basket line.
function renderBuyStrip(result) {
  const strip = $("buy-strip");
  const requisitionOnly = result.can_create_requisition && !result.can_add_to_cart;
  if (!result.can_add_to_cart && !result.can_create_requisition) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;

  const unattended = result.unattended && !requisitionOnly;
  const actionCopy = requisitionOnly
    ? "This agent follows a requisition workflow. RAMIFY will create a signed simulated requisition instead of placing the item in the consumer basket."
    : unattended
      ? "Your agent is authorised to complete this simulated purchase without a person. The receipt still controls the action."
      : "Your agent permits this purchase. Adding it creates a basket line backed by this exact signed receipt.";
  const buttonLabel = requisitionOnly
    ? "Create requisition"
    : unattended
      ? "Let the agent buy it"
      : "Add to basket";
  const buttonId = requisitionOnly ? "create-requisition" : "add-to-cart";

  strip.innerHTML = `
    <div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;">
      <div style="flex:1;min-width:240px;">
        <div style="font-family:var(--serif);font-size:18px;">${esc(result.product_name)}</div>
        <div style="font-size:13px;color:var(--ink-3);margin-top:2px;">${esc(actionCopy)}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-family:var(--serif);font-size:24px;font-weight:600;">${money(result.order.line_total_cents)}</div>
      </div>
      <button class="btn ${unattended ? "btn-go" : ""} btn-lg" id="${buttonId}">${esc(buttonLabel)}</button>
    </div>`;

  if (requisitionOnly) {
    $("create-requisition").addEventListener("click", createRequisition);
  } else {
    $("add-to-cart").addEventListener("click", addToCart);
  }
}

async function addToCart() {
  const button = $("add-to-cart");
  button.disabled = true;

  try {
    const result = await api("/api/v0/cart/add", { receipt_ref: current.receipt_ref });
    setBadge("cart-count", result.cart.item_count);
    button.classList.add("btn-go");
    button.textContent = current.unattended ? "Authorised ✓" : "Added ✓";
    toast("The receipt-backed basket line was recorded. Taking you to Basket…", "good");
    sessionStorage.setItem("ramify:just-added", result.line.line_id);
    setTimeout(() => { window.location.href = "/cart"; }, 650);
  } catch (error) {
    button.disabled = false;
    button.textContent = current?.unattended ? "Let the agent buy it" : "Add to basket";
    toast(error.message, "bad");
  }
}

async function createRequisition() {
  const button = $("create-requisition");
  button.disabled = true;
  try {
    const result = await api("/api/v0/requisition/create", { receipt_ref: current.receipt_ref });
    button.classList.add("btn-go");
    button.textContent = "Requisition recorded ✓";
    sessionStorage.setItem("ramify:just-requisitioned", result.requisition.requisition_id);
    toast("Signed simulated requisition created. No consumer basket line was added.", "good");
    refreshBadges();
    setTimeout(() => { window.location.href = "/cart"; }, 700);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Create requisition";
    toast(error.message, "bad");
  }
}

// Alternatives are optional assistance, not part of the authoritative decision.
// Keep this renderer isolated so a failed suggestion lookup can never interrupt
// the main RAMIFY result, receipt, checkout boundary or journey navigation.
async function renderAlternatives(result) {
  const slot = $("alternatives");
  if (!slot) return;

  slot.hidden = true;
  slot.innerHTML = "";
  if (!result?.requires_human || result.objective_posture === "block") return;

  slot.innerHTML = `<p class="placeholder">Looking for something this agent could use instead…</p>`;
  slot.hidden = false;

  try {
    const response = await api("/api/v0/alternatives", {
      identifier: result.subject_ref,
      actor_ref: $("actor").value,
      quantity: Number($("qty").value) || 1,
    });
    const alternatives = response?.alternatives;

    if (!alternatives?.candidates?.length) {
      slot.innerHTML = `<p class="placeholder">No suitable alternative in this local catalogue clears this agent's conditions.</p>`;
      return;
    }

    slot.innerHTML = `
      <p class="alternatives-intro">
        ${alternatives.because ? `${esc(alternatives.because)} ` : ""}
        Here ${alternatives.candidates.length === 1 ? "is" : "are"} ${alternatives.candidates.length}
        option${alternatives.candidates.length === 1 ? "" : "s"} that
        <strong>${esc(alternatives.actor_label)}</strong> can proceed with.
        <span>${esc(alternatives.note || "")}</span>
      </p>
      <div class="alt-grid">
        ${alternatives.candidates.map((c) => `
          <article class="alt-card ${c.is_named_replacement ? "named" : ""}">
            ${c.is_named_replacement ? '<div class="alt-flag">Named replacement</div>' : ""}
            <div class="alt-name">${esc(c.product_name)}</div>
            <div class="alt-meta">${esc(c.brand)}</div>
            <div class="alt-price">${money(c.line_total_cents)}</div>
            <div class="alt-why">
              <span class="pill pill-${c.actor_decision === "allow" ? "green" : "orange"}">${esc(c.actor_decision)}</span>
              ${esc(c.why || "Clears this agent's current conditions")}
            </div>
            <button class="btn btn-sm" type="button" data-alt="${esc(c.subject_ref)}">Check this product →</button>
          </article>`).join("")}
      </div>`;

    slot.querySelectorAll("[data-alt]").forEach((button) => {
      button.addEventListener("click", () => {
        const ref = button.dataset.alt;
        selectProduct(ref);
        // selectProduct prepares a human-readable request and an exact trusted
        // candidate, so this follow-up stays on the deterministic fast path.
        void run(selectedRequestText);
      });
    });
  } catch (error) {
    slot.innerHTML = `<p class="placeholder">Alternatives are temporarily unavailable. The RAMIFY decision above is unchanged.</p>`;
    console.warn("Alternative lookup failed", error);
  }
}

function renderTrace(result) {
  const timing = result.receipt?.latencies_us || {};
  const totalUs = Number(timing.total || 0);
  const totalMs = totalUs / 1000;
  const aiMs = Number(result.interpretation?.latency_ms);
  const combinedMs = totalMs + (Number.isFinite(aiMs) ? aiMs : 0);

  const rows = result.call_trace
    .map((step, i) => {
      const { label, tone } = traceTone(step, result);
      const latencyMs = Number(step.latency_us || 0) / 1000;
      return `
      <button type="button" class="trace-row trace-row-action" data-evidence-index="${i}" style="animation-delay:${i * 55}ms" aria-label="Open source evidence for ${esc(step.primitive)}">
        <span class="pname">${esc(step.primitive)}()</span>
        <span class="pin">${esc(step.input)}</span>
        <span><span class="pill pill-${tone}">${esc(label)}</span></span>
        <span class="trace-latency" title="Measured locally for this run">${latencyMs.toFixed(3)} ms</span>
        <span class="trace-evidence-cue">evidence →</span>
      </button>`;
    })
    .join("");

  const checks = result.receipt.check_results
    .map(
      (c) => `
      <div class="check">
        <span class="clabel">${esc(c.label)}</span>
        <span><span class="pill pill-${OUTCOME_PILL[c.outcome]}">${esc(c.outcome)}</span></span>
        <span class="cdetail">${esc(c.detail)}</span>
      </div>`
    )
    .join("");

  const primitiveCards = result.call_trace
    .map((step, i) => {
      const latencyMs = Number(step.latency_us || 0) / 1000;
      const { label, tone } = traceTone(step, result);
      return `<article class="primitive-proof-card tone-${tone}">
        <span>${String(i + 1).padStart(2, "0")}</span>
        <strong>${esc(step.primitive)}</strong>
        <small>Input: ${esc(step.input)}</small>
        <b>Output: ${esc(step.output)}</b>
        <em>${latencyMs.toFixed(3)} ms</em>
        <i>${esc(label)}</i>
      </article>`;
    })
    .join('<u aria-hidden="true">→</u>');

  $("trace").innerHTML = `
    <div class="performance-proof">
      <span><small>Interpretation</small><b>${Number.isFinite(aiMs) ? `${aiMs.toFixed(3)} ms` : "not measured"}</b></span>
      <span><small>Deterministic RAMIFY</small><b>${totalMs.toFixed(3)} ms</b></span>
      <span><small>Local total</small><b>${combinedMs.toFixed(3)} ms</b></span>
      <span><small>Receipt</small><b>signed + checkable</b></span>
      <p>AI latency is kept separate from deterministic trust-engine latency. These are local demo measurements, not production benchmarks.</p>
    </div>
    <div class="primitive-proof-workspace">
      <div class="trust-timeline-title"><span class="eyebrow">FIVE RESOLVE PRIMITIVES</span><strong>The deterministic proof at the centre of RAMIFY</strong></div>
      <div class="primitive-proof-track">${primitiveCards}</div>
      <p class="detail-note">The seven detailed evidence checks sit inside the verify stage. The model does not create any primitive output.</p>
    </div>
    ${rows}
    <div class="checks">
      <div class="field-label" style="margin-bottom:10px;">The seven detailed checks under verify()</div>
      ${checks}
    </div>`;
  $$("[data-evidence-index]", $("trace")).forEach((button) =>
    button.addEventListener("click", () => openEvidenceTrail(Number(button.dataset.evidenceIndex)))
  );
}

function renderConditions(result) {
  const intro = result.narrowed
    ? `<p style="margin:0;font-size:14px;">
         Your agent tightened this from <strong>${esc(result.objective_posture)}</strong> to
         <strong>${esc(result.actor_decision)}</strong>. Nothing about the product changed —
         every check above returns the same result for everyone. What changed is who is asking.
       </p>`
    : `<p style="margin:0;font-size:14px;">
         Your agent's conditions are all met, so the outcome stands at
         <strong>${esc(result.objective_posture)}</strong>.
       </p>`;
  $("conditions").innerHTML = intro + conditionList(result.conditions_evaluated);
}

function renderGate(result) {
  const nice = {
    purchase_autonomously: "authorise autonomous checkout",
    add_to_mock_cart: "continue to basket",
    create_mock_requisition: "create a procurement requisition",
    compare_alternatives: "compare alternatives",
    create_review_task: "send to human review",
    halt: "stop here",
  };

  const selected = result.selected_action;
  const permitted = result.permitted_actions || [];
  const selectedLabel = nice[selected] || selected.replaceAll("_", " ");
  const chips = permitted
    .map((action) => `<span class="action-permission ${action === selected ? "selected" : ""}">${esc(nice[action] || action.replaceAll("_", " "))}</span>`)
    .join("");

  const consequence = selected === "create_review_task"
    ? `<p class="action-note">This purchase receipt is already eligible for <a href="/review">Needs me</a>. Recording the Action Gate event does not create a second review.</p>`
    : selected === "create_mock_requisition"
      ? `<p class="action-note">The signed receipt can create a requisition in Step 6. It will not be placed in the consumer basket.</p>`
      : selected === "add_to_mock_cart" || selected === "purchase_autonomously"
        ? `<p class="action-note">The signed receipt can stage the real simulated transaction in Step 6. Recording this transition alone does not put anything in the basket.</p>`
        : selected === "halt"
          ? `<p class="action-note">No purchase transition is available. RAMIFY stops here and keeps the reason on the signed receipt.</p>`
          : "";

  const substitution = result.substitution
    ? `<div class="gate-substitution"><div><strong>A replacement relationship is on file</strong><span>${esc(result.substitution.replacement_name)} · ${esc(result.substitution.note)}</span></div><button class="btn btn-sm btn-ghost" id="go-substitute">Assess replacement →</button></div>`
    : "";

  $("gate").innerHTML = `
    <div class="gate-decision-card">
      <div><span class="eyebrow">SELECTED TRANSITION</span><h3>${esc(selectedLabel)}</h3><p>${esc(result.selected_action_description || "RAMIFY selected the next permitted transition from this agent policy.")}</p></div>
      <button class="btn btn-sm" id="record-selected-action">Record Action Gate event</button>
    </div>
    <div class="field-label" style="margin:14px 0 8px;">Permitted by this signed decision</div>
    <div class="action-permissions">${chips || '<span class="action-permission">none</span>'}</div>
    ${consequence}
    ${substitution}
    <div id="action-log"></div>`;

  $("record-selected-action")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const recorded = await recordAction(selected, selectedLabel);
    if (recorded) {
      button.textContent = "Recorded ✓";
      if (["add_to_mock_cart", "purchase_autonomously", "create_mock_requisition"].includes(selected)) {
        setTimeout(() => goJourney(4), 260);
      }
    } else {
      button.disabled = false;
    }
  });

  const substituteButton = $("go-substitute");
  if (substituteButton) substituteButton.addEventListener("click", () => run(result.substitution.superseded_by));
}

// Client direction, 5 August 2026: an action must produce an observable
// consequence and a recorded follow-on event, not just a toast.
async function recordAction(action, label) {
  try {
    const result = await api("/api/v0/action", {
      receipt_ref: current.receipt_ref,
      action,
    });
    toast(
      `Recorded: ${label}. Event ${result.event.event_id.slice(-8)} added to the trail. ` +
        "Nothing was purchased.",
      "good"
    );
    renderActionLog();
    return result;
  } catch (error) {
    toast(error.message, "bad");
    return null;
  }
}

async function renderActionLog() {
  const slot = $("action-log");
  if (!slot) return;
  const { events } = await api("/api/v0/actions?limit=6");
  const mine = events.filter((e) => e.receipt_ref === current.receipt_ref);
  if (!mine.length) {
    slot.innerHTML = "";
    return;
  }
  slot.innerHTML =
    `<div class="field-label" style="margin:14px 0 8px;">Recorded events for this decision</div>` +
    mine
      .map(
        (e) => `<div class="action-event">
          <span class="mono">${esc(e.recorded_at.slice(11, 19))}</span>
          <span>${esc(e.action.replace(/_/g, " "))}</span>
          <span class="mono" style="color:var(--ink-4);">#${esc(e.event_sequence || "—")} · ${esc(e.event_id.slice(-10))}</span>
          <span class="pill pill-info">simulated</span>
          <span class="event-hash">${esc(e.event_hash || "legacy event")}</span>
        </div>`
      )
      .join("");
}

// The receipt a buyer reads and the receipt an auditor reads are the same
// document at two depths. What is shown unprompted is what a person would want
// on a till receipt — what, when, for whom, and what was decided. Hashes,
// postures and raw JSON are all still here, one press away.
function renderReceipt(result) {
  const r = result.receipt;
  const light = result.traffic_light;
  const findings = r.check_results.filter((c) => c.outcome !== "pass");
  const evidenceValidity = r.check_results.find((c) => c.check_id === "evidence_freshness");
  const total = r.latencies_us ? r.latencies_us.total : null;
  const seal = { green: "✓", orange: "!", red: "✕" }[light.colour];

  const findingRows = findings.length
    ? findings
        .map(
          (c) => `<li><span class="pill pill-${OUTCOME_PILL[c.outcome]}">${esc(c.outcome)}</span>
                  <span><strong>${esc(c.label)}</strong> — ${esc(c.detail)}</span></li>`
        )
        .join("")
    : `<li><span class="pill pill-pass">pass</span>
        <span>All seven checks passed. Nothing was raised against this product.</span></li>`;

  $("human").innerHTML = `
    <div class="receipt-doc ${personaClass(result.actor_ref)}">
      <header class="receipt-head" data-receipt-summary>
        <div>
          <div class="receipt-brand">RAMIFY OS</div>
          <div class="receipt-kind">Decision receipt</div>
        </div>
        <div class="receipt-seal ${esc(light.colour)}">${seal}</div>
      </header>

      <dl class="receipt-fields receipt-essentials" data-receipt-summary>
        <dt>Product</dt><dd><strong>${esc(r.product_name || r.subject_ref)}</strong></dd>
        ${r.order ? `<dt>Order</dt><dd>${esc(r.order.quantity)} × ${money(r.order.unit_price_cents)} = <strong>${money(r.order.line_total_cents)}</strong></dd>` : ""}
        <dt>Receipt ID</dt><dd class="mono">${esc(r.receipt_id.replace("ramify:demo:rcpt:", ""))}</dd>
        <dt>Sealed</dt><dd>${esc(r.timestamp.replace("T", " ").slice(0, 19))} UTC</dd>
        <dt>Checked for</dt><dd><span class="persona-inline ${personaClass(result.actor_ref)}"><span class="persona-dot" aria-hidden="true"></span>${esc(r.actor_label)}</span></dd>
      </dl>

      <section class="receipt-verdict ${esc(light.colour)}" data-receipt-summary>
        <div class="receipt-block-title">Decision</div>
        <div class="receipt-verdict-line">${esc(light.label)}</div>
        <div class="receipt-verdict-sub">${esc(light.meaning)}</div>
      </section>

      <section class="receipt-status-grid" id="receipt-status-grid" data-receipt-summary aria-label="Receipt status summary">
        <span><small>Receipt integrity</small><b id="receipt-integrity-status">Checking…</b></span>
        <span><small>Evidence validity</small><b>${esc(evidenceValidity ? `${evidenceValidity.outcome}: ${evidenceValidity.detail}` : "Not recorded")}</b></span>
        <span><small>Permitted action</small><b>${esc((r.selected_action || (r.permitted_actions || [])[0] || "No purchase action").replaceAll("_", " "))}</b></span>
        <span><small>Purchase authority</small><b id="receipt-authority-status">Checking…</b></span>
      </section>

      <section class="receipt-block" data-receipt-summary>
        <div class="receipt-block-title">What this means</div>
        <div class="explanation-slot">
          <p id="explanation" class="placeholder">Writing it up…</p>
        </div>
        <p class="written-by" id="written-by"></p>
      </section>

      <div class="receipt-story-tabs" role="tablist" aria-label="Receipt views">
        <button class="active" type="button" data-receipt-tab="summary" role="tab" aria-selected="true">Summary</button>
        <button type="button" data-receipt-tab="evidence" role="tab" aria-selected="false">Evidence trail${findings.length ? ` · ${findings.length}` : ""}</button>
        <button type="button" data-receipt-tab="json" data-reveal="receipt-technical" role="tab" aria-selected="false">Signed JSON</button>
      </div>
      <div class="receipt-more">
        <button class="btn btn-sm btn-ghost" id="verify">✓ Verify receipt</button>
        <button class="btn btn-sm btn-ghost" id="download-receipt">↓ Export JSON</button>
        <button class="btn btn-sm btn-quiet" id="tamper-quick">Tamper demo</button>
      </div>

      <section class="receipt-reveal receipt-tab-panel" id="receipt-findings" data-receipt-panel="evidence" hidden>
        <ul class="receipt-list">${findingRows}</ul>
      </section>

      <section class="receipt-reveal receipt-tab-panel" id="receipt-technical" hidden data-receipt-panel="json">
        <div class="receipt-two">
          <div>
            <div class="receipt-block-title">Decision, as recorded</div>
            <dl class="receipt-fields">
              <dt>Objective posture</dt><dd class="mono">${esc(r.objective_posture)}</dd>
              <dt>Actor decision</dt><dd class="mono">${esc(r.actor_decision)}</dd>
              <dt>Selected action</dt><dd class="mono">${esc(r.selected_action)}</dd>
              <dt>Reason codes</dt>
              <dd class="mono">${esc((r.reason_codes || []).join(", ") || "none")}</dd>
            </dl>
          </div>
          <div>
            <div class="receipt-block-title">What it was judged against</div>
            <dl class="receipt-fields">
              <dt>Identity</dt><dd class="mono">${esc(r.canonical_state)}</dd>
              <dt>Standing</dt><dd>${esc(result.standing_display ? result.standing_display.user_facing : r.status_result.standing)}</dd>
              <dt>Policy</dt><dd class="mono">${esc(r.policy_ref)} v${esc(r.policy_version)}</dd>
              <dt>Dataset</dt><dd class="mono">${esc(r.data_snapshot)}</dd>
              ${total != null ? `<dt>Assessed in</dt><dd>${esc(total)} µs</dd>` : ""}
            </dl>
          </div>
        </div>

        <div class="receipt-block-title" style="margin-top:16px;">Stage timings</div>
        <div class="latency">${Object.entries(r.latencies_us || {})
          .map(([stage, us]) => `<span class="lat">${esc(stage)} ${esc(us)} µs</span>`)
          .join("")}</div>
        <p class="caveat">Measured on this machine against a twelve-product dataset held in
          memory, with no network and no database in the path. Recorded because the receipt
          carries them, not because they demonstrate anything about performance.</p>

        <div class="receipt-block-title" style="margin-top:16px;">Content hash</div>
        <div class="receipt-crypto mono">${esc(r.payload_hash)}</div>
        <div class="receipt-block-title" style="margin-top:12px;">Signature</div>
        <div class="receipt-crypto mono">${esc(r.signature)}</div>

        <div class="json" style="margin-top:16px;">
          <div class="json-bar">
            <span class="json-title">the signed receipt, exactly as stored</span>
            <button class="dark-btn" id="copy">COPY</button>
            <button class="dark-btn" id="tamper">TEST A CHANGED COPY</button>
          </div>
          <pre id="json">${esc(JSON.stringify(r, null, 2))}</pre>
        </div>
      </section>

      <footer class="receipt-foot">
        <div><strong>Sealed and checkable.</strong> Any later change to this receipt is
          detectable from the hash and signature it carries. Check it with the button above
          or with <span class="mono">scripts/ramify_verify.py</span> on any machine.</div>
        <div class="receipt-notice">${esc(r.notice)}</div>
      </footer>
    </div>`;

  $$("#human [data-receipt-tab]").forEach((button) =>
    button.addEventListener("click", () => {
      const tab = button.dataset.receiptTab;
      $$("#human [data-receipt-tab]").forEach((b) => {
        const active = b === button;
        b.classList.toggle("active", active);
        b.setAttribute("aria-selected", String(active));
      });
      $$("#human [data-receipt-summary]").forEach((node) => (node.hidden = tab !== "summary"));
      $$("#human [data-receipt-panel]").forEach((panel) => {
        const active = panel.dataset.receiptPanel === tab;
        panel.hidden = !active;
        panel.classList.toggle("revealed", active);
      });
    })
  );

  $("verify").addEventListener("click", () => verifyInto("terminal", current.receipt, false));
  void refreshReceiptStatusSummary(r);
  $("download-receipt").addEventListener("click", downloadCurrentReceipt);
  $("tamper-quick").addEventListener("click", async () => {
    await tamperTest();
    $("terminal").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  $("copy").addEventListener("click", copyReceipt);
  $("tamper").addEventListener("click", tamperTest);
}

async function refreshReceiptStatusSummary(receipt) {
  const integrity = $("receipt-integrity-status");
  const authority = $("receipt-authority-status");
  if (!integrity || !authority) return;
  try {
    const report = await api("/api/v0/receipt/verify", receipt);
    const intact = report.integrity_verified ?? report.verified;
    integrity.textContent = intact ? "Verified" : "Failed";
    integrity.className = intact ? "status-good" : "status-bad";
    if (report.purchase_authority_valid == null) {
      authority.textContent = "Not applicable";
      authority.className = "status-neutral";
    } else if (report.purchase_authority_valid) {
      authority.textContent = "Current";
      authority.className = "status-good";
    } else {
      authority.textContent = "Not current";
      authority.className = "status-warn";
    }
  } catch (error) {
    integrity.textContent = "Could not verify";
    authority.textContent = "Could not verify";
    integrity.className = authority.className = "status-warn";
  }
}

async function renderExplanation(receipt) {
  // The explanation never blocks the receipt, so a slow or absent local model
  // cannot hold up a demo.
  const node = $("explanation");
  try {
    const result = await api("/api/v0/explain", { receipt });
    if (!node.isConnected) return;
    node.classList.remove("placeholder");
    const authoritative = result.authoritative_summary || result.explanation;
    node.innerHTML = `<strong>Authoritative receipt summary:</strong> ${esc(authoritative)}` +
      (result.model_text_accepted && result.explanation !== authoritative
        ? `<br><br><strong>Optional AI explanation:</strong> ${esc(result.explanation)}`
        : "");
    const by = $("written-by");
    if (by) {
      by.textContent = result.model_text_accepted
        ? `Optional wording by ${agentSourceLabel(result.source)}. The deterministic receipt summary remains authoritative.`
        : "Written from the sealed receipt. The receipt and deterministic summary are authoritative.";
    }
  } catch {
    if (node.isConnected) {
      node.textContent = "No plain-English summary is available. The receipt is what counts.";
    }
  }
}

async function copyReceipt() {
  await copyText(JSON.stringify(current.receipt, null, 2), () =>
    toast("Copied. Check it yourself with: python scripts/ramify_verify.py receipt.json")
  );
}

// Forge whatever would most benefit someone holding this particular receipt.
// Setting `actor_decision` to "allow" on a receipt that already reads allow
// changes nothing, and a tamper test that alters nothing proves nothing.
async function tamperTest() {
  const altered = JSON.parse(JSON.stringify(current.receipt));

  if (altered.actor_decision === "allow") {
    altered.product_name = `${altered.product_name} (relabelled)`;
  } else {
    altered.actor_decision = "allow";
    altered.selected_action = "add_to_mock_cart";
    altered.permitted_actions = ["add_to_mock_cart"];
  }

  await verifyInto("terminal", altered, true);
}


// ── product trust experience layer ──────────────────────────────────────


function startFresh() {
  clearPreparedProduct({ keepQuery: false, preserveActor: false });
  $("qty").value = "1";
  setDrawer(false);
  window.scrollTo({ top: 0, behavior: "smooth" });
  toast("Fresh shopping view ready. Existing receipts and audit history were not deleted.", "good");
}

function renderTrustTimeline() {
  const slot = $("trust-timeline");
  if (!slot || !current) return;
  const milestones = [
    ["Request understood", 1],
    ["Product identified", 1],
    ["Evidence checked", 2],
    ["Agent policy applied", 3],
    ["Receipt signed", 4],
    ["Action controlled", 5],
  ];
  slot.innerHTML = `<div class="trust-timeline-title"><span class="eyebrow">RAMIFY TRUST TIMELINE</span><strong>One trace from language to controlled action</strong></div>
    <div class="trust-timeline-track">${milestones.map(([label, step], index) => {
      const anotherAtSameStageAfter = milestones.slice(index + 1).some(([, laterStep]) => laterStep === step);
      const state = journeyStep > step || (journeyStep === step && anotherAtSameStageAfter)
        ? "done"
        : journeyStep === step
          ? "active"
          : "upcoming";
      return `<span class="trust-timeline-node ${state}"><b>${state === "done" ? "✓" : index + 1}</b><small>${esc(label)}</small></span>${index < milestones.length - 1 ? '<i aria-hidden="true"></i>' : ''}`;
    }).join("")}</div>`;
}

function renderRiskPath(result) {
  const slot = $("risk-path");
  if (!slot) return;
  const hardStop = result.objective_posture === "block" || result.actor_decision === "block";
  const review = ["hold", "escalate"].includes(result.actor_decision);
  const final = hardStop ? "Locked stop" : review ? "Needs me" : "Permitted action";
  const tone = hardStop ? "red" : review ? "orange" : "green";
  slot.innerHTML = `<div class="risk-path tone-${tone}">
    <span><b>Request</b><small>understood</small></span><i>→</i>
    <span><b>RAMIFY</b><small>${esc(result.objective_posture.replaceAll("_", " "))}</small></span><i>→</i>
    <span><b>${esc(result.actor_label)}</b><small>${esc(result.actor_decision.replaceAll("_", " "))}</small></span><i>→</i>
    <span class="risk-path-final"><b>${esc(final)}</b><small>${hardStop ? "No persona can override a hard stop" : review ? "A person must decide" : "Only receipt-permitted actions remain"}</small></span>
  </div>`;
}

function renderWhyPanel(result) {
  const slot = $("why-panel");
  if (!slot) return;
  const findings = result.receipt?.check_results?.filter((c) => c.outcome !== "pass") || [];
  const primaryCondition = String(result.primary_reason || result.receipt?.primary_reason || "");
  const primary = findings.find((f) =>
    primaryCondition && (String(f.condition || "") === primaryCondition || String(f.reason_code || "") === primaryCondition)
  ) || findings[0];
  const policyRule = (result.applied_rules || [])[0];
  const policyReason = policyRule?.reason_code
    ? policyRule.reason_code.replaceAll("_", " ")
    : policyRule?.rule_id
      ? policyRule.rule_id.replaceAll("_", " ")
      : "this agent's configured buying policy";

  let title = "No blocking finding";
  let headline = "All product checks passed and this agent's conditions did not tighten the outcome.";
  let policyNote = "";

  if (result.narrowed) {
    title = "Agent policy";
    headline = `RAMIFY's product truth is ${String(result.objective_posture || "unknown").replaceAll("_", " ")}. ${result.actor_label} tightened the permitted outcome to ${String(result.actor_decision || "unknown").replaceAll("_", " ")} because of ${policyReason}.`;
    if (primary) {
      policyNote = `<p class="why-secondary"><strong>Product finding:</strong> ${esc(primary.label)} — ${esc(primary.detail)}</p>`;
    }
  } else if (primary) {
    title = primary.label;
    headline = primary.detail;
  }

  const extraFindings = findings.filter((f) => f !== primary).slice(0, 3);
  slot.innerHTML = `<details class="why-drawer"><summary><span>Why this result?</span><strong>${esc(title)}</strong></summary>
    <div><p>${esc(headline)}</p>${policyNote}${extraFindings.length ? `<ul>${extraFindings.map((f) => `<li><strong>${esc(f.label)}:</strong> ${esc(f.detail)}</li>`).join("")}</ul>` : ""}<button class="btn btn-sm btn-ghost" type="button" id="why-evidence">View source evidence</button></div>
  </details>`;
  $("why-evidence")?.addEventListener("click", () => openEvidenceTrail(0));
}

async function openEvidenceTrail(index = 0) {
  if (!current) return;
  const source = await api(`/api/v0/subject/${encodeURIComponent(current.subject_ref)}`);
  const step = current.call_trace?.[index];
  const panel = $("evidence-trail-panel");
  if (!panel) return;
  const evidence = (source.evidence || []).filter(Boolean);
  panel.hidden = false;
  panel.innerHTML = `<div class="evidence-trail-head"><div><span class="eyebrow">LIVE SOURCE EVIDENCE</span><strong>${esc(step?.primitive || "Product")} evidence trail</strong><p>These are the synthetic source records available to the deterministic RAMIFY checks for this product.</p></div><button class="btn btn-sm btn-quiet" type="button" id="close-evidence-trail">Close</button></div>
    <div class="evidence-trail-grid">
      <article><span>Product</span><strong>${esc(source.subject?.name || current.product_name)}</strong><small>${esc(source.subject?.brand || "")}</small></article>
      <article><span>Status</span><strong>${esc(source.status?.standing || source.status?.status || "No active standing")}</strong><small>${esc(source.status?.note || source.status?.reason || "Local synthetic status record")}</small></article>
      ${evidence.map((record, i) => `<article><span>Evidence ${i + 1}</span><strong>${esc(record?.kind || record?.type || record?.evidence_type || "Evidence record")}</strong><small>${esc(record?.issuer_ref || record?.issuer || record?.ref || "Synthetic issuer record")}</small><details><summary>Inspect record</summary><pre>${esc(JSON.stringify(record, null, 2))}</pre></details></article>`).join("")}
    </div>`;
  $("close-evidence-trail").addEventListener("click", () => (panel.hidden = true));
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function downloadCurrentReceipt() {
  if (!current?.receipt) return;
  const blob = new Blob([JSON.stringify(current.receipt, null, 2) + "\\n"], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${current.receipt.receipt_id.replaceAll(":", "-")}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  toast("Signed receipt JSON exported.", "good");
}

function renderSessionSummary(result) {
  const slot = $("session-summary");
  if (!slot) return;
  const totalMs = Number(result.receipt?.latencies_us?.total || 0) / 1000;
  const human = result.requires_human || ["hold", "escalate"].includes(result.actor_decision);
  slot.innerHTML = `<div class="session-summary-head"><span class="eyebrow">SESSION SUMMARY</span><strong>What happened in this shopping decision</strong></div>
    <div class="session-summary-grid">
      <span><small>Product</small><b>${esc(result.product_name)}</b></span>
      <span><small>Product truth</small><b>${esc(result.objective_posture.replaceAll("_", " "))}</b></span>
      <span class="${personaClass(result.actor_ref)}"><small>Agent policy</small><b><span class="persona-dot" aria-hidden="true"></span>${esc(result.actor_label)}</b></span>
      <span><small>Permitted outcome</small><b>${esc(result.actor_decision.replaceAll("_", " "))}</b></span>
      <span><small>RAMIFY time</small><b>${totalMs.toFixed(3)} ms</b></span>
      <span><small>Human review</small><b>${human ? "Required" : "Not required"}</b></span>
      <span><small>Receipt</small><b>Signed · ${esc(result.receipt_ref?.slice(-10) || result.receipt?.receipt_id?.slice(-10))}</b></span>
    </div>
    <div class="session-summary-actions"><button class="btn btn-sm btn-ghost" type="button" id="summary-passport">Open Trust Passport</button><button class="btn btn-sm btn-quiet" type="button" id="summary-restart">Start fresh</button></div>`;
  $("summary-passport")?.addEventListener("click", () => openTrustPassport(result.subject_ref, result));
  $("summary-restart")?.addEventListener("click", startFresh);
}


startPage(boot);

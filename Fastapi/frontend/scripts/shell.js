"use strict";

// Shared across every page. Plain JavaScript, no framework, no build step.
//
// Nothing here decides anything. Verdicts arrive already sealed inside a
// receipt; this draws them and derives the traffic-light colour at display
// time, which is why no colour is ever stored.

const $ = (id) => document.getElementById(id);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const money = (cents) =>
  cents == null
    ? "—"
    : `A$${(cents / 100).toLocaleString("en-AU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;

// Light persona identity colours. These are deliberately separate from the
// green / amber / red trust-state colours, so the UI can show who acted
// without changing the meaning of the decision.
const PERSONA_TONE = Object.freeze({
  consumer_v1: "consumer",
  autonomous_buyer_v1: "autonomous",
  budget_guard_v1: "budget",
  brand_loyal_v1: "brand",
  procurement_v1: "procurement",
});

function personaTone(actorRef) {
  return PERSONA_TONE[String(actorRef || "")] || "custom";
}

function personaClass(actorRef) {
  return `persona-tone persona-${personaTone(actorRef)}`;
}

function agentSourceLabel(source) {
  const raw = String(source || "");
  if (raw.startsWith("langgraph+ollama:")) {
    const model = raw.slice("langgraph+ollama:".length) || "local model";
    return `Local AI · LangGraph + Ollama · ${model}`;
  }
  if (raw.includes("langgraph")) return "Local AI · LangGraph";
  if (raw === "exact_identifier") return "Exact product identifier";
  if (raw === "selected_catalogue_item") return "Selected catalogue item";
  if (raw === "deterministic_fallback") return "Safe deterministic fallback";
  if (raw === "deterministic_catalogue_search") return "Safe catalogue matcher";
  if (raw === "deterministic_summary") return "Receipt-derived summary";
  return raw || "Local processing";
}

async function api(path, body, method) {
  const options = { method: method || (body ? "POST" : "GET") };
  if (body) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error(
      "The local RAMIFY server could not be reached. Keep the server window open and refresh this page."
    );
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      if (response.ok) {
        throw new Error(`RAMIFY returned an unreadable response from ${path}.`);
      }
      payload = { detail: text.slice(0, 240) };
    }
  }

  if (!response.ok) {
    const detail = payload && payload.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || "Invalid request").join("; ")
      : detail || `${path} → ${response.status}`;
    throw new Error(String(message));
  }
  return payload;
}

function showPageError(error) {
  console.error(error);
  let panel = $("page-load-error");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "page-load-error";
    panel.className = "page-load-error";
    panel.setAttribute("role", "alert");
    const main = document.querySelector("main") || document.body;
    main.prepend(panel);
  }
  panel.innerHTML = `
    <strong>This page could not finish loading.</strong>
    <span>${esc(error?.message || "Unexpected local error")}</span>
    <button type="button" class="btn btn-sm btn-ghost" onclick="window.location.reload()">Try again</button>`;
}

function startPage(bootFunction) {
  Promise.resolve().then(bootFunction).catch((error) => {
    showPageError(error);
    toast(error?.message || "This page could not load.", "bad");
  });
}

// The clipboard is blocked in some browsers. A selectable dialog beats an
// unexplained failure in front of an audience.
async function copyText(text, onSuccess) {
  try {
    await navigator.clipboard.writeText(text);
    onSuccess();
    return true;
  } catch {
    let dialog = $("copy-fallback");
    if (!dialog) {
      document.body.insertAdjacentHTML(
        "beforeend",
        `<dialog id="copy-fallback">
           <h3>Copy this</h3>
           <p style="font-size:13px;color:var(--ink-3);margin-top:0;">
             Your browser would not let the page reach the clipboard, so here it is to select
             by hand.</p>
           <pre id="copy-fallback-body"></pre>
           <div class="dialog-actions">
             <button class="btn btn-ghost"
               onclick="document.getElementById('copy-fallback').close()">Close</button>
           </div>
         </dialog>`
      );
      dialog = $("copy-fallback");
    }
    $("copy-fallback-body").textContent = text;
    dialog.showModal();
    return false;
  }
}

function toast(message, kind) {
  let node = $("toast");
  if (!node) {
    node = document.createElement("div");
    node.id = "toast";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    node.setAttribute("aria-atomic", "true");
    document.body.appendChild(node);
  }
  node.className = `toast${kind ? " " + kind : ""}`;
  node.setAttribute("role", kind === "bad" ? "alert" : "status");
  node.setAttribute("aria-live", kind === "bad" ? "assertive" : "polite");
  node.textContent = message;
  requestAnimationFrame(() => node.classList.add("show"));
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("show"), 3400);
}

// ── shell ────────────────────────────────────────────────────────────────

const NAV = [
  ["/shop", "Shop", "", "shop"],
  ["/agents", "My agents", "", "agents"],
  ["/review", "Needs me", "review-count", "review"],
  ["/cart", "Basket", "cart-count", "basket"],
  ["/activity", "Activity", "", "activity"],
  ["/human-receipt", "Human receipts", "", "human"],
  ["/about", "About", "", "about"],
  ["/help", "Help", "", "help"],
];

const NAV_ICON = Object.freeze({
  shop: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5h16l-1.2 10H5.2L4 9.5Z"/><path d="M8 10V7.5a4 4 0 0 1 8 0V10"/></svg>`,
  agents: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.8 19c.4-3.2 2.4-5 5.2-5s4.8 1.8 5.2 5"/><circle cx="17.2" cy="9.2" r="2.2"/><path d="M15.2 14.7c3.1-.6 5 .8 5.3 3.6"/></svg>`,
  review: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4.5 6v5.8c0 4.3 2.8 7.3 7.5 9.2 4.7-1.9 7.5-4.9 7.5-9.2V6L12 3Z"/><path d="m8.7 12 2.1 2.1 4.5-4.6"/></svg>`,
  basket: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8h14l-1.1 11H6.1L5 8Z"/><path d="m8 8 2.2-4h3.6L16 8"/></svg>`,
  activity: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17h3l2.2-6 3.1 8 2.5-11 2.1 6H20"/></svg>`,
  human: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4M9 11h6M9 15h6"/></svg>`,
  about: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.2"/></svg>`,
  help: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.7 9a2.5 2.5 0 1 1 3.4 2.35c-.8.35-1.1.9-1.1 1.65v.3M12 17h.01"/></svg>`,
});
function navLink([href, label, badgeId, icon]) {
  const active = href === document.body.dataset.route ? ' aria-current="page"' : "";
  const badge = badgeId ? ` <span class="count" id="${badgeId}" hidden></span>` : "";
  return `<a href="${href}"${active}><span class="nav-icon">${NAV_ICON[icon] || ""}</span><span>${label}</span>${badge}</a>`;
}

function mountShell(current) {
  document.body.dataset.route = current;
  const primary = NAV.slice(0, 6).map(navLink).join("");
  const secondary = NAV.slice(6).map(navLink).join("");

  document.body.insertAdjacentHTML(
    "afterbegin",
    `<header class="topbar">
       <div class="topbar-inner">
         <a class="brand" href="/shop" aria-label="RAMIFY OS — open shop">
           <span class="brand-mark" aria-hidden="true">R</span>
           <span class="brand-copy"><span class="wordmark">RAMIFY OS</span><span class="tagline">Product trust, explained clearly</span></span>
         </a>
         <nav class="nav-primary" aria-label="Main navigation">${primary}</nav>
         <div class="topbar-separator" aria-hidden="true"></div>
         <nav class="nav-secondary" aria-label="Information">${secondary}</nav>
         <div class="topbar-right">
           <span class="offline" id="offline-badge" title="Reported by the backend health endpoint">
             <span class="dot"></span><span id="offline-text">CHECKING…</span></span>
         </div>
       </div>
     </header>`
  );

  refreshBadges();
  reportConfiguration();
  installFinalPolish();
}

// The badge reports what the backend says about itself rather than asserting a
// fact the page cannot know. A static label would claim more than it proves.
async function reportConfiguration() {
  const text = $("offline-text");
  if (!text) return;
  try {
    const [health, agent] = await Promise.all([
      api("/healthz"),
      api("/api/v0/agent/status").catch(() => null),
    ]);
    if (agent?.active_mode === "deterministic_fallback" && agent?.local_model_available) {
      text.textContent = agent.presentation_state === "slow_fallback" ? "AI SLOW · SAFE FALLBACK" : "AI FALLBACK ACTIVE";
      $("offline-badge").classList.remove("local-ai-ready");
      $("offline-badge").title = `${agent.presentation_detail || "The local model did not complete."} The deterministic RAMIFY engine remains the decision authority.`;
    } else if (agent?.local_model_available) {
      text.textContent = `LOCAL AI · ${String(agent.model || "MODEL").toUpperCase()}`;
      $("offline-badge").classList.add("local-ai-ready");
      $("offline-badge").title =
        `Local AI is available: ${agent.framework} + ${agent.provider} + ${agent.model}. ` +
        `The model interprets requests and explains sealed receipts only; ` +
        `the deterministic RAMIFY engine remains the decision authority.`;
    } else {
      text.textContent = (health.documented_launch_loopback_only ?? health.default_launcher_loopback_only)
        ? "LOCAL · AI FALLBACK"
        : "BACKEND REACHABLE";
      $("offline-badge").title =
        `Local AI is not active (${agent?.detail || "status unavailable"}). ` +
        `RAMIFY is using its deterministic fallback. Build ${health.build}.`;
    }
  } catch {
    text.textContent = "BACKEND UNREACHABLE";
    $("offline-badge").classList.add("offline-bad");
  }
}

async function refreshBadges() {
  try {
    const [queue, basket] = await Promise.all([api("/api/v0/review/queue"), api("/api/v0/cart")]);
    setBadge("review-count", queue.open.length);
    setBadge("cart-count", basket.item_count);
  } catch {
    /* offline badge state is not worth an error message */
  }
}

function setBadge(id, count) {
  const badge = $(id);
  if (!badge) return;
  const previous = badge.textContent;
  badge.textContent = count;
  badge.hidden = !count;
  if (String(count) !== previous && count) {
    badge.classList.remove("ui-count-pop");
    requestAnimationFrame(() => badge.classList.add("ui-count-pop"));
    badge.addEventListener("animationend", () => badge.classList.remove("ui-count-pop"), { once: true });
  }
}

async function mountFooter() {
  // Scoped to a direct child of body: pages carry their own <footer> elements
  // inside panels and drawers, and a bare `querySelector("footer")` finds
  // whichever appears first in the document rather than the page's own.
  const footer = document.querySelector("body > footer");
  if (!footer) return;
  const cat = await catalogue();
  footer.innerHTML =
    `<div>Policy ${esc(cat.policy.policy_ref)} v${esc(cat.policy.policy_version)} ` +
    `(${esc(cat.policy.status.replace(/_/g, " "))}) · dataset ${esc(cat.data_snapshot)} · ` +
    `every date evaluated against ${esc(cat.snapshot_date.slice(0, 10))}</div>` +
    `<div>Synthetic data. Not for real purchasing, safety, legal or compliance decisions. ` +
    `· <a href="/help">Need a hand?</a> · build ${esc(cat.build)}</div>`;
}

const PRODUCT_IMAGE_BY_SUBJECT = Object.freeze({
  "ramify:demo:supp:apex-mg-glyc-120": "/apex-magnesium-glycinate.png",
  "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z": "/brightway-vitd3-2024-11-z.png",
  "ramify:demo:supp:brightway-vitd3-5000-b2025-06-M": "/brightway-vitd3-2025-06-m.png",
  "ramify:demo:supp:greenline-ashw-ksm66-90": "/greenline-ashwagandha.png",
  "ramify:demo:supp:northbeam-vitc-1000-b2025-03-A": "/northbeam-vitamin-c.png",
  "ramify:demo:supp:tidalpoint-omega3-1000-b2025-12-D": "/tidalpoint-omega3.png",
  "ramify:demo:supp:stonefield-zinc-gluc-50-90": "/stonefield-zinc-gluconate.png",
  "ramify:demo:supp:stonefield-zinc-picolinate-50-90": "/stonefield-zinc-picolinate.png",
  "ramify:demo:supp:ridgeway-multivit-b2026-02-C": "/ridgeway-multivitamin.png",
  "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K": "/harborline-nitrile-gloves.png",
  "ramify:demo:ppe:covelane-n95-resp-b2026-01-B": "/covelane-n95.png",
  "ramify:demo:ppe:merridale-faceshield-std": "/merridale-face-shield.png",
});

function productImage(subjectRef) {
  return PRODUCT_IMAGE_BY_SUBJECT[subjectRef] || "";
}


// ── small product-experience helpers ────────────────────────────────────
function personaFingerprint(profile) {
  if (!profile) return "";
  const autonomy = {
    none: "Human first",
    clean_only: "Clean only",
    clean_or_warned: "High autonomy",
  }[profile.autonomy_level] || "Controlled";
  const budget = profile.budget_limit_cents == null ? "No ceiling" : money(profile.budget_limit_cents);
  const brands = profile.brand_allowlist?.length ? `${profile.brand_allowlist.length} brand rule${profile.brand_allowlist.length === 1 ? "" : "s"}` : "Any brand";
  const sellers = profile.approved_vendors?.length ? `${profile.approved_vendors.length} seller rule${profile.approved_vendors.length === 1 ? "" : "s"}` : "Any seller";
  return `<div class="persona-fingerprint" aria-label="Policy fingerprint">
    <span><small>Autonomy</small><b>${esc(autonomy)}</b></span>
    <span><small>Budget</small><b>${esc(budget)}</b></span>
    <span><small>Brand</small><b>${esc(brands)}</b></span>
    <span><small>Seller</small><b>${esc(sellers)}</b></span>
  </div>`;
}

async function openTrustPassport(subjectRef, assessment = null) {
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const cat = await catalogue();
  const product = cat.products.find((p) => p.subject_ref === subjectRef);
  if (!product) return;
  const source = await api(`/api/v0/subject/${encodeURIComponent(subjectRef)}`);
  let dialog = $("trust-passport-dialog");
  if (!dialog) {
    document.body.insertAdjacentHTML("beforeend", `<dialog id="trust-passport-dialog" class="trust-passport-dialog">
      <button class="trust-passport-x" type="button" id="trust-passport-x" aria-label="Close trust passport">×</button>
      <div id="trust-passport-body"></div>
      <div class="dialog-actions"><button class="btn btn-ghost" type="button" id="trust-passport-close">Close</button></div>
    </dialog>`);
    dialog = $("trust-passport-dialog");
    $("trust-passport-x").addEventListener("click", () => dialog.close());
    $("trust-passport-close").addEventListener("click", () => dialog.close());
  }
  dialog._returnFocus = opener;
  if (!dialog.dataset.focusReturnBound) {
    dialog.addEventListener("close", () => {
      const target = dialog._returnFocus;
      if (target && document.contains(target)) target.focus();
    });
    dialog.dataset.focusReturnBound = "1";
  }
  const status = source.status || {};
  const evidence = (source.evidence || []).filter(Boolean);
  const currentResult = assessment && assessment.subject_ref === subjectRef ? assessment : null;
  const posture = currentResult?.objective_posture;
  const decision = currentResult?.actor_decision;
  const freshness = currentResult?.receipt?.check_results?.find((check) =>
    String(check.label || "").toLowerCase().includes("fresh")
  );
  const receiptId = currentResult?.receipt?.receipt_id;
  const sealedAt = currentResult?.receipt?.timestamp;
  $("trust-passport-body").innerHTML = `
    <div class="trust-passport-head">
      <div class="trust-passport-image"><img src="${esc(productImage(subjectRef))}" alt="${esc(product.name)}"></div>
      <div><span class="eyebrow">PRODUCT TRUST PASSPORT</span><h3>${esc(product.name)}</h3><p>${esc(product.brand)} · ${esc(product.seller_name)} · ${money(product.price_cents)}</p></div>
    </div>
    <div class="trust-passport-grid">
      <span><small>Catalogue identity</small><b>Known product</b></span>
      <span><small>Batch / model</small><b>${esc(product.batch_ref || "Not batch-specific")}</b></span>
      <span><small>Evidence records</small><b>${evidence.length}</b></span>
      <span><small>Evidence validity</small><b>${esc(freshness ? `${freshness.outcome}: ${freshness.detail}` : "Run RAMIFY to calculate")}</b></span>
      <span><small>Recorded standing</small><b>${esc(status.standing || status.status || "No active status record")}</b></span>
      <span><small>Latest objective result</small><b>${esc(posture || "Not assessed in this session")}</b></span>
      <span><small>Latest agent decision</small><b>${esc(decision || "Not assessed in this session")}</b></span>
      <span><small>Latest signed receipt</small><b>${esc(receiptId ? receiptId.slice(-14) : "No receipt in this session")}</b></span>
      <span><small>Last sealed</small><b>${esc(sealedAt ? sealedAt.replace("T", " ").slice(0, 19) + " UTC" : "Not assessed in this session")}</b></span>
    </div>
    <div class="trust-passport-proof">
      <strong>What this passport means</strong>
      <p>These are the local synthetic records RAMIFY can inspect for this catalogue item. A trust decision is only created when you deliberately run RAMIFY; browsing this passport creates no purchase authority.</p>
    </div>
    <details class="trust-passport-sources"><summary>View source records</summary><pre>${esc(JSON.stringify(source, null, 2))}</pre></details>`;
  dialog.showModal();
}
function initBeforeAfter() {
  const root = $("before-after");
  if (!root) return;
  $$("[data-ba]", root).forEach((button) => button.addEventListener("click", () => {
    const mode = button.dataset.ba;
    $$("[data-ba]", root).forEach((b) => {
      const active = b.dataset.ba === mode;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", String(active));
    });
    $$("[data-ba-panel]", root).forEach((panel) => {
      const active = panel.dataset.baPanel === mode;
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    });
  }));
}

let _catalogue = null;
async function catalogue(force) {
  if (force) _catalogue = null;
  if (!_catalogue) _catalogue = await api("/api/v0/catalogue");
  return _catalogue;
}

// ── traffic light ────────────────────────────────────────────────────────

// Green is a clean approval, orange means a warning or human attention, and red is a hard stop.
// The machine posture travels in the receipt, so colour never has to carry the full meaning.
function renderLight(light, posture, aside = "") {
  return `
    <div class="light light-${esc(light.colour)}">
      <div class="lamp"></div>
      <div class="light-text">
        <div class="label">${esc(light.label)}</div>
        <div class="meaning">${esc(light.meaning)}</div>
        ${light.warning ? `<div class="warn-chip">There is a finding attached — worth reading first</div>` : ""}
      </div>
      <div class="light-aside">
        system code<span class="posture">${esc(posture)}</span>
        <span class="mapping-note">mapping ${esc(light.mapping_version || "")}</span>${aside}
      </div>
    </div>`;
}

// Two answers to two different questions, shown as two fields. What the
// evidence says is the same for everybody; what this agent may do with it is
// not. Collapsing them into one number hides the distinction the whole
// architecture exists to make.
function renderVerdictSplit(result) {
  const objective = result.objective_light;
  const actor = result.traffic_light;
  const narrowed = result.narrowed;

  const reason = narrowed
    ? (result.applied_rules[0] &&
        {
          warned_outcome_requires_review:
            "The assessment carried a warning, and this agent sends those to a person.",
          seller_not_on_approved_vendor_list:
            "The seller is genuine but is not on this agent's approved supplier list.",
          over_budget: "The line total is over this agent's spending limit.",
          brand_not_on_allowlist: "The brand is outside this agent's arrangement.",
        }[result.applied_rules[0].rule_id]) ||
      "This agent's own policy tightened the outcome."
    : "This agent's rules do not make the result any stricter.";

  return `
    <div class="split">
      <div class="split-half">
        <div class="split-label"><span class="sr-only">Objective product posture: </span>Product result</div>
        <div class="split-sub">What the evidence says before any agent rules are applied</div>
        <div class="split-value tone-${esc(objective.colour)}">${esc(objective.machine_posture)}</div>
        <div class="split-user">${esc(objective.label)}</div>
      </div>
      <div class="split-arrow ${narrowed ? "narrowed" : ""}" aria-label="Agent policy handoff">
        <span>Agent policy</span>
        <b aria-hidden="true">→</b>
      </div>
      <div class="split-half split-agent ${personaClass(result.actor_ref)}">
        <div class="split-label"><span class="persona-dot" aria-hidden="true"></span>${esc(result.actor_label)} response</div>
        <div class="split-sub">What this agent is allowed to do with the product result</div>
        <div class="split-value tone-${esc(actor.colour)}">${esc(actor.machine_posture)}</div>
        <div class="split-user">${esc(actor.label)}</div>
      </div>
      <div class="split-reason ${narrowed ? "narrowed" : ""}">
        <strong>Reason:</strong> ${esc(reason)}
      </div>
    </div>`;
}

// Each kind of stop gets its own accent and words — a recall and a spending
// limit both halt the agent but are not the same event.
function renderEscalation(escalation, actorLabel) {
  if (!escalation) return "";
  const human = escalation.requires_human;
  const chain = human
    ? `<div class="handover">
         <span class="node done">Agent asks</span><span class="link">→</span>
         <span class="node done">Checks run</span><span class="link">→</span>
         <span class="node stopped">Agent stops</span><span class="link">→</span>
         <span class="node waiting">You decide</span>
       </div>`
    : `<div class="handover">
         <span class="node done">Agent asks</span><span class="link">→</span>
         <span class="node done">Checks run</span><span class="link">→</span>
         <span class="node stopped">Agent will not proceed</span>
       </div>`;

  return `
    <div class="escalation esc-${esc(escalation.tone)}">
      <div class="esc-head">
        <div class="esc-mark">${esc(escalation.icon)}</div>
        <div>
          <h3>${esc(escalation.headline)}</h3>
          <p>${esc(escalation.body)}</p>
        </div>
      </div>
      ${chain}
      <div class="esc-who">
        <span class="who-label">Who decides</span>
        <span class="who-value">${esc(escalation.decided_by)}</span>
        ${human ? `<span class="agent-paused">◼ ${esc(actorLabel)} paused</span>` : ""}
        ${human ? `<a class="btn btn-sm btn-ghost" href="/review">Open what needs me →</a>` : ""}
      </div>
    </div>`;
}

function conditionList(conditions) {
  if (!conditions || !conditions.length) {
    return `<p class="placeholder">This agent holds no conditions of its own. It takes the
            product assessment exactly as it stands.</p>`;
  }
  return `<div class="conditions">${conditions
    .map(
      (c) => `
      <div class="condition ${c.met ? "met" : "unmet"}">
        <span class="mark">${c.met ? "✓" : "!"}</span>
        <span>
          <span class="clabel">${esc(c.label)}</span>
          <span class="kind-tag ${c.kind === "commercial" ? "commercial" : ""}">${esc(
            c.kind.replace(/_/g, " ")
          )}</span>
          <div class="cdetail">${esc(c.detail)}</div>
        </span>
      </div>`
    )
    .join("")}</div>`;
}

// ── receipt verification ─────────────────────────────────────────────────

async function verifyInto(terminalId, receipt, wasTampered) {
  const report = await api("/api/v0/receipt/verify", receipt);
  const terminal = $(terminalId);
  const width = Math.max(...report.checks.map((c) => c.name.length));

  terminal.hidden = false;
  const integrityVerified = report.integrity_verified ?? report.verified;
  terminal.classList.toggle("bad", !integrityVerified);
  const integrityLine = integrityVerified
    ? "Receipt integrity: VERIFIED."
    : "Receipt integrity: FAILED.";
  const authorityLine = report.purchase_authority_valid == null
    ? "Purchase authority: not applicable to this record type."
    : report.purchase_authority_valid
      ? "Purchase authority: CURRENT."
      : "Purchase authority: NOT CURRENT. The sealed record may still be authentic.";
  terminal.textContent = [
    "$ ramify-verify < receipt.json",
    "",
    ...report.checks.map(
      (c) => `  ${c.name.padEnd(width)}  ${c.passed ? "ok  " : "FAIL"}  ${c.detail}`
    ),
    "",
    integrityLine,
    authorityLine,
    "",
    wasTampered
      ? "One field was changed in a copy of the receipt above. The stored hash no longer\n" +
        "describes the stored content, so verification rejected it. The receipt on screen\n" +
        "is untouched."
      : "Checked by the same code the standalone ramify-verify tool runs. Only the checks\n" +
        "listed above were performed; none are asserted without being run.",
  ].join("\n");
  const seal = document.querySelector(".receipt-seal, .guided-receipt-seal, .walkthrough-receipt-seal");
  if (seal && integrityVerified) {
    seal.classList.remove("seal-verified");
    requestAnimationFrame(() => seal.classList.add("seal-verified"));
  }
  return report;
}

async function openInspector(subjectRef) {
  const data = await api(`/api/v0/subject/${subjectRef}`);
  let dialog = $("inspector");
  if (!dialog) {
    document.body.insertAdjacentHTML(
      "beforeend",
      `<dialog id="inspector">
         <h3>Synthetic source record</h3>
         <p style="font-size:13px;color:var(--ink-3);margin-top:0;">
           Returned by the local backend for this product. Shown so the inputs can be read
           alongside the answer.
         </p>
         <pre id="inspector-body"></pre>
         <div class="dialog-actions">
           <button class="btn btn-ghost" onclick="document.getElementById('inspector').close()">Close</button>
         </div>
       </dialog>`
    );
    dialog = $("inspector");
  }
  $("inspector-body").textContent = JSON.stringify(data, null, 2);
  dialog.showModal();
}

// ── first-run welcome ───────────────────────────────────────────────────
// A simple choice for a first-time viewer. It is shown once per browser tab
// session so completing the interactive tour can return to the Shop without
// immediately opening the same dialog again. Help always links back to /tour.
function mountFirstRunWelcome() {
  if (sessionStorage.getItem("ramify-welcome-seen") === "1") return;

  const dialog = document.createElement("dialog");
  dialog.id = "welcome-choice";
  dialog.className = "welcome-choice";
  dialog.innerHTML = `
    <div class="welcome-aurora" aria-hidden="true"><span></span><span></span><span></span></div>
    <button type="button" class="welcome-close" id="welcome-close" aria-label="Close and open the shop"><span>×</span></button>
    <div class="welcome-grid">
      <section class="welcome-story">
        <div class="welcome-mark"><span>R</span><i aria-hidden="true"></i></div>
        <div class="eyebrow">WELCOME TO RAMIFY OS</div>
        <h2>See how RAMIFY checks a purchase before action.</h2>
        <p>Choose the shop or the guided tour. RAMIFY keeps the evidence, policy and signed receipt trail clear underneath.</p>
        <div class="welcome-journey" aria-label="RAMIFY journey preview">
          <span><b>1</b><small>Choose</small></span>
          <i></i>
          <span><b>2</b><small>Check</small></span>
          <i></i>
          <span><b>3</b><small>Decide</small></span>
          <i></i>
          <span><b>4</b><small>Receipt</small></span>
        </div>
        <div class="welcome-trust-note"><span class="welcome-trust-pulse" aria-hidden="true"></span><strong>AI helps interpret.</strong><span>RAMIFY keeps the trust decision deterministic.</span></div>
      </section>
      <section class="welcome-actions-panel">
        <div class="welcome-actions-head"><span>Choose your view</span><small>You can switch later</small></div>
        <div class="welcome-options">
          <button type="button" class="welcome-option" id="welcome-demo">
            <span class="welcome-option-top"><span class="welcome-option-icon">↗</span><em>Explore</em></span>
            <strong>Explore the demo myself</strong>
            <small>Open the shop, choose any product and move through the journey at your own pace.</small>
            <span class="welcome-option-action">Open shop <b>→</b></span>
          </button>
          <button type="button" class="welcome-option featured" id="welcome-tour">
            <span class="welcome-option-top"><span class="welcome-option-icon">◎</span><em>Recommended</em></span>
            <strong>Guide me through the full tour</strong>
            <small>Follow a highlighted step-by-step journey from product choice to receipt and the protected checkout boundary.</small>
            <span class="welcome-option-action">Start guided tour <b>→</b></span>
          </button>
        </div>
        <p class="welcome-foot">The guided tour is a fast deterministic walkthrough. You can replay it later from Help.</p>
      </section>
    </div>`;
  document.body.appendChild(dialog);

  const remember = () => sessionStorage.setItem("ramify-welcome-seen", "1");
  const openShop = () => { remember(); window.location.href = "/shop"; };
  $("welcome-demo").onclick = openShop;
  $("welcome-tour").onclick = () => { remember(); window.location.href = "/tour"; };
  $("welcome-close").onclick = openShop;
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); openShop(); });
  dialog.showModal();

  // Presentation-only depth for the first-run choice. It never changes flow or data.
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduceMotion && matchMedia("(hover:hover) and (pointer:fine)").matches) {
    let frame = 0;
    dialog.addEventListener("pointermove", (event) => {
      const rect = dialog.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * 100;
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        dialog.style.setProperty("--welcome-x", `${x.toFixed(1)}%`);
        dialog.style.setProperty("--welcome-y", `${y.toFixed(1)}%`);
      });
    }, { passive: true });
  }
}

// ── Client-final interface polish ───────────────────────────────────────
// Presentation-only behaviour. It never reads, writes or changes a decision.
function installFinalPolish() {
  if (document.documentElement.dataset.finalPolish === "1") return;
  document.documentElement.dataset.finalPolish = "1";

  // Mark the shared shell as ready without observing or mutating every section.
  requestAnimationFrame(() => document.documentElement.classList.add("ui-ready"));

  // Keep a clear keyboard focus mode for live demos and accessibility.
  let keyboardMode = false;
  document.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      keyboardMode = true;
      document.documentElement.classList.add("ui-keyboard");
    }
  });
  document.addEventListener("pointerdown", () => {
    if (!keyboardMode) return;
    keyboardMode = false;
    document.documentElement.classList.remove("ui-keyboard");
  }, { passive: true });

  installAdvancedMotion();
}
function installAdvancedMotion() {
  if (document.documentElement.dataset.advancedMotion === "1") return;
  document.documentElement.dataset.advancedMotion = "1";

  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const saveData = !!navigator.connection?.saveData;
  const motionOK = !reduceMotion && !saveData;
  document.documentElement.classList.toggle("ui-motion-ok", motionOK);
  document.documentElement.classList.add("ui-motion-lite");
}
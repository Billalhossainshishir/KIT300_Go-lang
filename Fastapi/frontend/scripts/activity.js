"use strict";

// The history, written as sentences rather than a table of postures —
// "actor_decision: hold" is a field name, not an answer. The record itself is
// one click away for anyone who wants it.

const LIGHT_OF = {
  allow: "green",
  allow_with_warning: "orange",
  hold: "orange",
  escalate: "orange",
  block: "red",
};

const SENTENCE = {
  allow: (r) => `${r.actor_label} checked ${bold(r.product_name)} and found nothing wrong with it.`,
  allow_with_warning: (r) =>
    `${r.actor_label} cleared ${bold(r.product_name)}, with something worth knowing attached.`,
  hold: (r) => `${r.actor_label} stopped on ${bold(r.product_name)} and asked you to decide.`,
  escalate: (r) =>
    `${r.actor_label} could not tell enough about ${bold(r.product_name)} to judge it, so it asked you.`,
  block: (r) => `${r.actor_label} refused ${bold(r.product_name)} outright.`,
};

const BECAUSE = {
  active_recall_on_batch: "it is under an active recall",
  active_advisory_on_batch: "it is under an active advisory",
  claim_rejected_or_revoked: "an issuer withdrew one of its claims",
  evidence_expired: "its lab certificate has passed its date",
  mandatory_evidence_missing: "required paperwork is missing",
  required_claim_missing: "nobody has claimed what is required",
  issuers_state_conflicting_values: "two sources disagree about it",
  claim_asserted_outside_issuer_authority: "a claim came from a body with no standing",
  seller_authority_unverified_for_category: "the seller's authority is not established",
  identity_unresolved: "it matched no product on file",
  identity_ambiguous: "it matched more than one product",
  line_total_exceeds_agent_budget: "the known total is over the agent's spending limit",
  line_total_unavailable_for_agent_budget: "the price is unavailable, so the agent cannot evaluate its spending limit",
  brand_outside_agent_arrangement: "the brand is outside the agent's arrangement",
  seller_not_on_approved_vendor_list: "the seller is not on the approved list",
  autonomy_withheld_on_warned_outcome: "the agent will not buy a warned item unattended",
  warned_outcome_requires_a_person: "warnings were set to always come to you",
  procurement_policy_requires_review_of_warned_outcome: "policy sends anything warned to a person",
  superseded_product_available: "a newer version exists",
  status_unknown: "no recall record is held for it",
  no_evidence_to_assess: "there is nothing on file to assess",
  no_claims_to_compare: "there are no claims to compare",
  not_run_identity_unresolved: "the rest of the checks could not run",
};

const bold = (text) => `<strong>${esc(text)}</strong>`;

let feed = [];
let superseded = new Set();

async function boot() {
  mountShell("/activity");
  mountFooter();
  $("filter").addEventListener("change", render);
  $("include-comparisons").addEventListener("change", render);
  $("check-all").addEventListener("click", checkAll);
  $("verify-actions").addEventListener("click", verifyActions);
  await load();
  await loadActions();
  await loadTransactions();
}

async function load() {
  const data = await api("/api/v0/receipts?limit=200");
  feed = data.receipts;
  superseded = new Set(data.superseded);
  render();
}

function render() {
  const filter = $("filter").value;
  const includeComparisons = $("include-comparisons").checked;

  // A comparison runs one real assessment per agent and each writes a real
  // receipt. Nothing is hidden; they are filtered out by default so the one
  // decision that mattered is not buried under the exploratory ones.
  const nonDecisionContexts = new Set(["guided_demo", "interactive_tour", "suggestion", "proof_pack"]);
  const hiddenWalkthroughCount = feed.filter((r) => nonDecisionContexts.has(r.assessment_context)).length;
  const comparisonCount = feed.filter((r) => r.assessment_context === "comparison").length;
  const visible = feed.filter((r) => {
    if (nonDecisionContexts.has(r.assessment_context)) return false;
    return includeComparisons || r.assessment_context !== "comparison";
  });

  const rows = visible.filter((r) => {
    if (filter === "all") return true;
    if (filter === "reviewed") return !!r.human_review || superseded.has(r.receipt_id);
    return LIGHT_OF[r.actor_decision] === filter;
  });

  if (!rows.length) {
    $("feed").innerHTML = `<div class="empty-state">
      <div class="glyph">◇</div>
      <div class="big">Nothing here yet.</div>
      <div>Check a product and it will show up.</div>
      <div style="margin-top:20px;"><a class="btn btn-ghost" href="/shop">Go shopping</a></div>
    </div>`;
    return;
  }

  $("feed").innerHTML =
    `<p style="font-size:13px;color:var(--ink-3);margin:0 0 14px;">
       ${rows.length} of ${visible.length} decision receipt${visible.length === 1 ? "" : "s"} shown${
         comparisonCount && !includeComparisons
           ? ` · ${comparisonCount} comparison run${comparisonCount === 1 ? "" : "s"} hidden`
           : ""
       }${hiddenWalkthroughCount ? ` · ${hiddenWalkthroughCount} guided/exploratory receipt${hiddenWalkthroughCount === 1 ? "" : "s"} kept out of this decision view` : ""}</p>` + rows.map(entry).join("");

  $$("[data-verify]").forEach((b) =>
    b.addEventListener("click", async () => {
      const receipt = feed.find((r) => r.receipt_id === b.dataset.verify);
      await verifyInto("terminal", receipt, false);
      $("terminal").scrollIntoView({ block: "nearest", behavior: "smooth" });
    })
  );
}

function entry(r) {
  const light = LIGHT_OF[r.actor_decision] || "orange";
  const sentence = (SENTENCE[r.actor_decision] || (() => esc(r.actor_decision)))(r);

  const reasons = (r.reason_codes || []).map((c) => BECAUSE[c]).filter(Boolean);
  const because = reasons.length
    ? `<div class="queue-why">Because ${
        reasons.length === 1
          ? reasons[0]
          : reasons.slice(0, -1).join("; ") + "; and " + reasons.at(-1)
      }.</div>`
    : "";

  const review = r.human_review
    ? `<div class="queue-why" style="color:var(--brand);">
         You then ${
           r.human_review.outcome === "confirmed"
             ? "agreed and left it."
             : "authorised this simulated transaction once."
         }
         The earlier record still reads <strong>${esc(
           r.human_review.reviewed_decision
         )}</strong> and was never altered.
       </div>`
    : "";

  const wasSuperseded = superseded.has(r.receipt_id)
    ? `<div class="queue-why" style="color:var(--ink-4);">You decided on this one later. Kept as it
       was issued.</div>`
    : "";

  const when = new Date(r.timestamp.replace(/(\.\d{3})\d+Z$/, "$1Z"));
  const stamp = isNaN(when) ? r.timestamp.slice(0, 19).replace("T", " ") : when.toLocaleString();

  return `
    <div class="queue-item ${light === "red" ? "severe" : light === "green" ? "done" : ""} ${personaClass(r.actor_ref)}">
      <div class="queue-head">
        <span class="qname" style="font-family:var(--sans);font-size:14.5px;font-weight:400;">
          ${sentence}</span>
        <span class="pill pill-${light}">${esc(r.actor_decision)}</span>
      </div>
      ${because}
      ${review}
      ${wasSuperseded}
      <div class="audit-story-row">
        <span><small>What happened</small><b>${esc(r.actor_decision.replaceAll("_", " "))}</b></span>
        <span class="${personaClass(r.actor_ref)}"><small>Who decided</small><b><span class="persona-dot" aria-hidden="true"></span>${esc(r.actor_label)}</b></span>
        <span><small>Why</small><b>${esc((r.primary_reason || (r.reason_codes || [])[0] || "no blocking reason").replaceAll("_", " "))}</b></span>
        <span><small>Proof</small><b>signed · ${esc(r.receipt_id.slice(-10))}</b></span>
      </div>
      <div class="queue-meta">
        ${esc(stamp)}${
          r.order ? ` · ${esc(r.order.quantity)} × ${money(r.order.unit_price_cents)}` : ""
        } · ${esc(r.receipt_id.slice(-12))}
      </div>
      <div class="queue-actions">
        ${r.human_review ? `<a class="btn btn-sm btn-ghost" href="/human-receipt?receipt=${encodeURIComponent(r.receipt_id)}">Open human receipt</a>` : ""}
        <button class="btn btn-sm btn-quiet" data-verify="${esc(r.receipt_id)}">
          Prove this one is unchanged</button>
      </div>
    </div>`;
}


async function loadActions() {
  const { events } = await api("/api/v0/actions?limit=50");
  const slot = $("action-events");
  if (!events.length) {
    slot.innerHTML = `<p class="placeholder">No Action Gate event has been recorded yet.</p>`;
    return;
  }
  slot.innerHTML = events.map((event) => `
    <div class="action-ledger-event">
      <span class="event-seq">${esc(event.event_sequence || "—")}</span>
      <div>
        <strong>${esc(event.action.replaceAll("_", " "))}</strong> · ${esc(event.product_name || event.subject_ref)}
        <div class="queue-meta">${esc(event.recorded_at)} · receipt ${esc((event.receipt_ref || "").slice(-14))}</div>
        <div class="event-hash">${esc(event.event_hash || "legacy event without chain hash")}</div>
      </div>
    </div>`).join("");
}


async function loadTransactions() {
  const data = await api("/api/v0/cart");
  const slot = $("transaction-records");
  if (!slot) return;
  const transactions = [
    ...(data.orders || []).map((record) => ({ kind: "order", record, at: record.timestamp || "" })),
    ...(data.requisitions || []).map((record) => ({ kind: "requisition", record, at: record.timestamp || "" })),
  ].sort((a, b) => String(b.at).localeCompare(String(a.at)));

  if (!transactions.length) {
    slot.innerHTML = `<p class="placeholder">No signed order or requisition has been recorded yet.</p>`;
    return;
  }

  slot.innerHTML = transactions.map(({ kind, record }) => {
    const isOrder = kind === "order";
    const id = isOrder ? record.order_id : record.requisition_id;
    const label = isOrder ? "Simulated order" : "Procurement requisition";
    const total = Number(record.total_cents ?? record.line_total_cents ?? 0);
    const count = isOrder ? Number(record.item_count || record.line_count || 0) : Number(record.quantity || 0);
    const summary = isOrder
      ? `${count} item${count === 1 ? "" : "s"} · ${money(total)}`
      : `${count} × ${esc(record.product_name || record.subject_ref || "product")} · ${money(total)}`;
    return `<article class="transaction-audit-card ${isOrder ? "is-order" : "is-requisition"}">
      <div class="transaction-audit-icon" aria-hidden="true">${isOrder ? "✓" : "R"}</div>
      <div class="transaction-audit-copy">
        <span class="eyebrow">${esc(label)}</span>
        <strong>${summary}</strong>
        <p>${esc(record.customer_summary?.headline || record.notice || "Signed synthetic transaction record.")}</p>
        <div class="queue-meta">${esc(record.timestamp || "Time not recorded")} · ${esc((id || "").slice(-14))}</div>
      </div>
      <button class="btn btn-sm btn-ghost" type="button" data-verify-transaction="${esc(id || "")}">Verify signed record</button>
    </article>`;
  }).join("");

  $$('[data-verify-transaction]', slot).forEach((button) => {
    button.addEventListener("click", async () => {
      const found = transactions.find(({ kind, record }) =>
        (kind === "order" ? record.order_id : record.requisition_id) === button.dataset.verifyTransaction
      );
      if (!found) return;
      await verifyInto("terminal", found.record, false);
      $("terminal").scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  });
}

async function verifyActions() {
  const report = await api("/api/v0/actions/verify");
  const terminal = $("terminal");
  terminal.hidden = false;
  terminal.classList.toggle("bad", !report.valid);
  terminal.textContent = [
    "$ verify-action-ledger",
    "",
    `events checked  ${report.total}`,
    `chain valid     ${report.valid ? "yes" : "NO"}`,
    `head hash       ${report.head_hash}`,
    "",
    ...(report.problems || []).map((p) => `event ${p.sequence}: ${p.problem}`),
    report.note,
  ].join("\n");
  terminal.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function checkAll() {
  const button = $("check-all");
  button.disabled = true;
  button.textContent = "Checking…";

  let intact = 0;
  let expired = 0;
  const broken = [];

  for (const receipt of feed) {
    const report = await api("/api/v0/receipt/verify", receipt);
    const sound =
      report.hash_valid && report.signature_valid && (report.issuer_refs_known ?? report.issuer_chain_valid) && report.scope_valid;
    if (!sound) broken.push({ id: receipt.receipt_id, report });
    else if (!report.fresh) expired++;
    else intact++;
  }

  const terminal = $("terminal");
  terminal.hidden = false;
  terminal.classList.toggle("bad", broken.length > 0);
  terminal.textContent = [
    `Checked ${feed.length} record${feed.length === 1 ? "" : "s"}.`,
    "",
    `  unchanged since issued   ${intact + expired}`,
    `  past their one-hour window ${expired}   (still unchanged — only the purchase-authority validity window lapsed)`,
    `  altered                  ${broken.length}`,
    "",
    ...broken.flatMap((b) => [
      `  ${b.id}`,
      ...b.report.checks.filter((c) => !c.passed).map((c) => `    ${c.name}: ${c.detail}`),
    ]),
    broken.length
      ? ""
      : "Every record still matches the seal it was issued with. Nothing has been edited.",
  ].join("\n");

  button.disabled = false;
  button.textContent = "Verify receipt history";
}

startPage(boot);

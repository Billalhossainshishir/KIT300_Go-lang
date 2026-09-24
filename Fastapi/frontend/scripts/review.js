"use strict";

// What is waiting on a person — the other half of the handover the shop shows.
//
// Deciding appends a linked record rather than editing the original, and the
// interface shows that: an answered item still carries its original outcome
// next to what the person then chose.

const REASON_TEXT = {
  active_advisory_on_batch: "this batch is under an active advisory",
  active_recall_on_batch: "this batch is under an active recall",
  evidence_expired: "the lab certificate behind it has passed its date",
  evidence_not_yet_valid: "a certificate behind it does not take effect until later",
  evidence_expiry_not_supplied: "a certificate behind it carries no expiry date at all",
  evidence_revoked: "the issuing body withdrew a certificate behind it",
  evidence_issuer_inactive: "the body that issued a certificate is no longer active",
  evidence_required_fields_missing: "an evidence record is missing fields it must carry",
  evidence_integrity_metadata_missing: "the evidence record is missing integrity metadata",
  evidence_artefact_missing: "the evidence artefact cannot be found",
  evidence_issuer_key_unknown: "the issuer public key is not in the demo trust material",
  evidence_storage_path_invalid: "the evidence artefact path is outside the trusted demo data area",
  evidence_hash_mismatch: "the evidence artefact bytes no longer match the signed hash",
  evidence_signature_invalid: "the issuer signature over the evidence artefact does not verify",
  evidence_subject_scope_mismatch: "the evidence is not bound to the product being assessed",
  seller_unknown: "the seller is not one the system holds a record for",
  seller_authority_unverified_for_category:
    "the seller's authority to supply this category is not established",
  issuers_state_conflicting_values: "two sources state different things about it",
  mandatory_evidence_missing: "paperwork this category requires is not attached",
  required_claim_missing: "nobody has actually claimed what this category requires",
  claim_rejected_or_revoked: "an issuer withdrew one of the product's claims",
  claim_asserted_outside_issuer_authority: "a claim came from a body with no standing to make it",
  identity_unresolved: "the identifier matches no product on file",
  identity_ambiguous: "the identifier matches more than one product",
  line_total_exceeds_agent_budget: "the known total is over your agent's spending limit",
  line_total_unavailable_for_agent_budget: "the price is unavailable, so your agent cannot evaluate its spending limit",
  brand_outside_agent_arrangement: "the brand is outside your agent's arrangement",
  autonomy_withheld_on_warned_outcome: "your agent will not buy a warned item unattended",
  warned_outcome_requires_a_person: "you asked to see anything carrying a warning",
  procurement_policy_requires_review_of_warned_outcome:
    "procurement policy sends anything warned to a person",
  seller_not_on_approved_vendor_list: "the seller is not on the approved list",
  superseded_product_available: "there is a newer version of this product",
  status_unknown: "no recall record is held for it",
  no_evidence_to_assess: "there is nothing on file to assess",
  no_claims_to_compare: "there are no claims on file to compare",
  not_run_identity_unresolved: "the rest of the checks could not run",
};

const TONE_OF = {
  safety: "severe",
  identity: "unknown",
  integrity: "severe",
  evidence: "caution",
  authority: "caution",
  price_unavailable: "commercial",
  budget: "commercial",
  arrangement: "commercial",
};

function why(receipt) {
  const reasons = (receipt.reason_codes || []).map((c) => REASON_TEXT[c]).filter(Boolean);
  if (!reasons.length) return "No reason was recorded.";
  if (reasons.length === 1) return `Stopped because ${reasons[0]}.`;
  return `Stopped because ${reasons.slice(0, -1).join("; ")}; and ${reasons.at(-1)}.`;
}

// Same classification the shop uses, so an item does not change character
// between the two screens.
function toneOf(receipt) {
  const codes = receipt.reason_codes || [];
  for (const [kind, tone] of Object.entries(TONE_OF)) {
    const groups = {
      safety: [
        "active_recall_on_batch",
        "active_advisory_on_batch",
        "claim_rejected_or_revoked",
        "evidence_revoked",
      ],
      identity: ["identity_unresolved", "identity_ambiguous", "not_run_identity_unresolved"],
      integrity: [
        "evidence_integrity_metadata_missing",
        "evidence_artefact_missing",
        "evidence_issuer_key_unknown",
        "evidence_storage_path_invalid",
        "evidence_hash_mismatch",
        "evidence_signature_invalid",
        "evidence_subject_scope_mismatch",
      ],
      evidence: [
        "evidence_expired",
        "evidence_not_yet_valid",
        "evidence_expiry_not_supplied",
        "evidence_issuer_inactive",
        "evidence_required_fields_missing",
        "mandatory_evidence_missing",
        "required_claim_missing",
        "issuers_state_conflicting_values",
        "claim_asserted_outside_issuer_authority",
        "no_evidence_to_assess",
        "no_claims_to_compare",
        "status_unknown",
      ],
      authority: [
        "seller_authority_unverified_for_category",
        "seller_authority_revoked",
        "seller_unknown",
      ],
      price_unavailable: ["line_total_unavailable_for_agent_budget"],
      budget: ["line_total_exceeds_agent_budget"],
      arrangement: [
        "brand_outside_agent_arrangement",
        "seller_not_on_approved_vendor_list",
        "procurement_policy_requires_review_of_warned_outcome",
        "warned_outcome_requires_a_person",
        "autonomy_withheld_on_warned_outcome",
      ],
    };
    if (codes.some((c) => groups[kind].includes(c))) return tone;
  }
  return "caution";
}

async function boot() {
  mountShell("/review");
  mountFooter();
  await load();
}

async function load() {
  const data = await api("/api/v0/review/queue");

  $("queue").innerHTML = data.open.length
    ? data.open.map(openItem).join("")
    : `<div class="empty-state">
         <div class="glyph">✓</div>
         <div class="big">Nothing needs you.</div>
         <div>Your agents have not stopped on anything.</div>
         <div style="margin-top:20px;"><a class="btn btn-ghost" href="/shop">Go shopping</a></div>
       </div>`;

  $("resolved").innerHTML = data.resolved.length
    ? data.resolved.map(resolvedItem).join("")
    : `<div class="empty-state"><div>You have not decided anything yet.</div></div>`;

  const byId = Object.fromEntries(data.open.map((r) => [r.receipt_id, r]));

  $$("[data-decide]").forEach((b) =>
    b.addEventListener("click", () => decide(b.dataset.receipt, b.dataset.decide, b))
  );
  $$("[data-verify]").forEach((b) =>
    b.addEventListener("click", async () => {
      const receipt = await api(`/api/v0/receipt/${b.dataset.verify}`);
      await verifyInto("terminal", receipt, false);
      $("terminal").scrollIntoView({ block: "nearest", behavior: "smooth" });
    })
  );
  $$("[data-detail]").forEach((b) =>
    b.addEventListener("click", () => {
      const panel = $(`detail-${b.dataset.detail}`);
      const opening = panel.hidden;
      if (opening && !panel.innerHTML) panel.innerHTML = detailPanel(byId[b.dataset.detail]);
      panel.hidden = !opening;
      panel.classList.toggle("revealed", opening);
      b.setAttribute("aria-expanded", String(opening));
      b.textContent = opening ? "Hide the detail" : "Why it needs you";
    })
  );
  $$("[data-compare]").forEach((b) =>
    b.addEventListener("click", () => compare(byId[b.dataset.compare], b))
  );

  refreshBadges();
}

// The same suggestion engine the shop uses, reached from the queue. Somebody
// working through what their agents stopped on should be able to resolve an
// item here rather than going back to the shop to look for a substitute.
async function compare(receipt, button) {
  const panel = $(`compare-${receipt.receipt_id}`);
  if (!panel.hidden) {
    panel.hidden = true;
    button.textContent = "Compare alternatives";
    return;
  }

  panel.hidden = false;
  panel.classList.add("revealed");
  button.textContent = "Hide alternatives";
  panel.innerHTML = `<p class="placeholder">Looking for something this agent could buy…</p>`;

  const { alternatives } = await api("/api/v0/alternatives", {
    identifier: receipt.subject_ref,
    actor_ref: receipt.actor_ref,
    quantity: receipt.order ? receipt.order.quantity : 1,
  });

  if (!alternatives || !alternatives.candidates.length) {
    panel.innerHTML = `<p class="placeholder">Nothing else in the catalogue clears
      ${esc(receipt.actor_label)}'s conditions either. This one really is your decision.</p>`;
    return;
  }

  panel.innerHTML = `
    <h4>What ${esc(receipt.actor_label)} could buy instead</h4>
    <p class="detail-note">${esc(alternatives.note)}</p>
    <div class="alt-grid">
      ${alternatives.candidates
        .map(
          (c) => `
        <div class="alt-card ${c.is_named_replacement ? "named" : ""}">
          ${c.is_named_replacement ? '<div class="alt-flag">the maker\'s own replacement</div>' : ""}
          <div class="alt-name">${esc(c.product_name)}</div>
          <div class="alt-meta">${esc(c.brand)}</div>
          <div class="alt-price">${money(c.line_total_cents)}</div>
          <div class="alt-why"><span class="pill pill-${
            c.actor_decision === "allow" ? "green" : "orange"
          }">${esc(c.actor_decision)}</span> ${esc(c.why)}</div>
          <a class="btn btn-sm" href="/?subject=${encodeURIComponent(
            c.subject_ref
          )}&actor=${encodeURIComponent(receipt.actor_ref)}">Take me to it</a>
        </div>`
        )
        .join("")}
    </div>`;
}

// Three kinds of stop, and they need different words. "Your own rule" and
// "nothing on file to judge" and "a finding against the product" are not
// variations on each other. Derived from the objective posture rather than
// from the reason codes, so a new code cannot quietly get filed as a finding.
function stopKind(r) {
  if (["allow", "allow_with_warning"].includes(r.objective_posture)) return "commercial";
  if (r.objective_posture === "escalate") return "incomplete";
  return "finding";
}

function openItem(r) {
  const commercial = stopKind(r) === "commercial";
  return `
    <div class="queue-item ${esc(toneOf(r))} ${personaClass(r.actor_ref)}" id="item-${esc(r.receipt_id)}">
      <div class="queue-head">
        <span class="qname">${esc(r.product_name || r.subject_ref)}</span>
        <span class="pill pill-orange">${esc(r.actor_decision)}</span>
        <span class="qactor persona-inline ${personaClass(r.actor_ref)}"><span class="persona-dot" aria-hidden="true"></span>stopped by ${esc(r.actor_label)}</span>
      </div>
      <div class="queue-why">${esc(why(r))}</div>
      <div class="queue-meta">${esc(r.receipt_id)} · sealed ${esc(r.timestamp)}</div>
      <div class="queue-actions">
        <button class="btn btn-sm btn-stop" data-decide="confirmed" data-receipt="${esc(r.receipt_id)}">
          Decline — leave item</button>
        <button class="btn btn-sm btn-go" data-decide="overridden" data-receipt="${esc(r.receipt_id)}">
          Authorise once</button>
        <button class="btn btn-sm btn-ghost" data-detail="${esc(r.receipt_id)}"
                aria-expanded="false">Why it needs you</button>
        ${
          commercial
            ? `<button class="btn btn-sm btn-quiet" data-compare="${esc(r.receipt_id)}">
                 Compare alternatives</button>`
            : ""
        }
        <button class="btn btn-sm btn-quiet" data-verify="${esc(r.receipt_id)}">Check the record</button>
      </div>
      <label class="review-note-label">Decision note (optional)
        <textarea class="review-note" id="note-${esc(r.receipt_id)}" maxlength="600"
          placeholder="Record why you accepted or declined this simulated transaction."></textarea>
      </label>
      <div class="queue-detail" id="detail-${esc(r.receipt_id)}" hidden></div>
      <div class="queue-detail" id="compare-${esc(r.receipt_id)}" hidden></div>
    </div>`;
}

// Plain English first, the machine record under it. Somebody deciding whether
// to overrule their agent needs the sentence; somebody auditing the decision
// needs the codes. Neither should have to leave the page for the other.
const WHAT_HAPPENED = {
  commercial: (r) => `The checks raised nothing that would stop anyone buying this — the
    product's own assessment came back <strong>${esc(r.objective_posture)}</strong>. It stopped
    here because of a rule you gave <strong>${esc(r.actor_label)}</strong>, and your agent will
    not quietly spend past its own instructions.`,
  incomplete: () => `There is not enough on file to judge this one either way. Nothing bad is
    recorded against it — the evidence a decision would rest on is missing, and the agent is
    saying so rather than rounding the gap up to a yes.`,
  finding: (r) => `Something is recorded against this product itself. The assessment came back
    <strong>${esc(r.objective_posture)}</strong> before any of your agent's own rules were
    applied, so it would read the same for any buyer.`,
};

const OVERRIDE_ADVICE = {
  commercial: "Reasonable here — the stop was your own rule, not a finding about the product.",
  incomplete:
    "You would be accepting it without the evidence, which is a real choice but should be a " +
    "deliberate one.",
  finding: "Read the findings below first; this one is a finding about the product.",
};

function detailPanel(r) {
  const kind = stopKind(r);
  const checks = r.check_results
    .map(
      (c) => `
      <div class="check">
        <span class="clabel">${esc(c.label)}</span>
        <span><span class="pill pill-${esc(c.outcome)}">${esc(c.outcome)}</span></span>
        <span class="cdetail">${esc(c.detail)}</span>
      </div>`
    )
    .join("");

  return `
    <div class="detail-plain">
      <h4>What happened</h4>
      <p>${WHAT_HAPPENED[kind](r)}</p>
      <p><strong>Why:</strong> ${esc(why(r))}</p>
      ${r.primary_reason ? `<p><strong>The deciding reason:</strong> ${esc(r.primary_reason)}.</p>` : ""}
      <h4>What your two choices do</h4>
      <ul>
        <li><strong>Decline — leave item.</strong> No basket line or requisition is created. A linked human
          receipt records that a person reviewed the stop and chose not to proceed.</li>
        <li><strong>Authorise once.</strong> A linked human receipt records that a person accepted
          responsibility for this simulated transaction only. ${esc(OVERRIDE_ADVICE[kind])}</li>
      </ul>
      <p class="detail-note">Either way the receipt below is left exactly as it is. Your decision
        is written next to it as its own linked record, never over it.</p>
    </div>

    <details class="detail-technical">
      <summary>The technical record</summary>
      <div class="detail-technical-body">
        <dl class="receipt-fields">
          <dt>Objective posture</dt><dd class="mono">${esc(r.objective_posture)}</dd>
          <dt>Actor decision</dt><dd class="mono">${esc(r.actor_decision)}</dd>
          <dt>Matched rule</dt><dd class="mono">precedence rule ${esc(r.objective_matched_rule)}</dd>
          <dt>Reason codes</dt><dd class="mono">${esc((r.reason_codes || []).join(", ") || "none")}</dd>
          <dt>Permitted actions</dt><dd class="mono">${esc((r.permitted_actions || []).join(", "))}</dd>
          <dt>Policy</dt><dd class="mono">${esc(r.policy_ref)} v${esc(r.policy_version)}</dd>
          <dt>Content hash</dt><dd class="mono">${esc(r.payload_hash)}</dd>
        </dl>
        <div class="checks">
          <div class="field-label" style="margin-bottom:10px;">The seven checks</div>
          ${checks}
        </div>
      </div>
    </details>`;
}

function resolvedItem(r) {
  const upheld = r.human_review.outcome === "confirmed";
  return `
    <div class="queue-item done ${personaClass(r.actor_ref)}">
      <div class="queue-head">
        <span class="qname">${esc(r.product_name || r.subject_ref)}</span>
        <span class="pill pill-${upheld ? "fail" : "pass"}">${
          upheld ? "left alone" : "authorised once"
        }</span>
        <span class="qactor persona-inline ${personaClass(r.actor_ref)}"><span class="persona-dot" aria-hidden="true"></span>${esc(r.actor_label)}</span>
      </div>
      <div class="queue-why">
        ${upheld
          ? "You agreed with your agent and left it."
          : "You authorised this simulated transaction once. The original machine decision remains unchanged."}
      </div>
      <div class="queue-meta">
        this record ${esc(r.receipt_id)}<br>
        follows on from ${esc(r.supersedes_receipt)}, which still reads
        <strong>${esc(r.human_review.reviewed_decision)}</strong> and was never altered
      </div>
      <div class="queue-actions">
        <a class="btn btn-sm btn-ghost" href="/human-receipt?receipt=${encodeURIComponent(r.receipt_id)}">Open human receipt</a>
        <button class="btn btn-sm btn-quiet" data-verify="${esc(r.receipt_id)}">Check the record</button>
      </div>
    </div>`;
}

async function decide(receiptId, outcome, button) {
  // Receipt ids contain colons, which a CSS selector will not take.
  // getElementById accepts the raw value. Reviewer identity is intentionally
  // not exposed as another form step in the client demo; the API's synthetic
  // defaults are written into the linked Human Receipt.
  const card = $(`item-${receiptId}`);
  if (card) $$("button", card).forEach((b) => (b.disabled = true));
  const typedNote = $(`note-${receiptId}`)?.value.trim();
  const note = typedNote ||
    (outcome === "confirmed"
      ? "Reviewed and declined for this simulated transaction."
      : "Reviewed and authorised once for this simulated transaction.");

  const result = await api("/api/v0/receipt/review", {
    receipt_id: receiptId,
    outcome,
    reviewer_note: note,
  });

  if (card) card.classList.add("resolving");
  if (outcome === "overridden") {
    const actions = result.receipt?.human_authorised_actions || [];
    const requisition = actions.includes("create_mock_requisition");
    const endpoint = requisition ? "/api/v0/requisition/create" : "/api/v0/cart/add";
    try {
      await api(endpoint, { receipt_ref: result.receipt_ref });
      toast(
        requisition
          ? "Human receipt created. A simulated requisition was recorded; the original machine receipt was not altered."
          : "Human receipt created. The simulated item was added to the basket; the original machine receipt was not altered.",
        "good"
      );
    } catch (error) {
      toast(`Human decision recorded, but the transaction step was refused: ${error.message}`, "bad");
    }
  } else {
    toast(`Human receipt ${result.receipt_ref.slice(-8)} recorded. The original machine receipt was not altered.`);
  }
  setTimeout(load, 540);
}

startPage(boot);

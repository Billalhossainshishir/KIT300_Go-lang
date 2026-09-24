"use strict";

async function boot() {
  mountShell("/human-receipt");
  mountFooter();
  const data = await api("/api/v0/receipts?limit=100");
  const reviews = data.receipts.filter((r) => r.human_review);
  render(reviews);

  const wanted = new URLSearchParams(location.search).get("receipt");
  if (wanted) {
    const target = document.getElementById(`human-${wanted}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function downloadReceipt(receipt) {
  const blob = new Blob([JSON.stringify(receipt, null, 2) + "\n"], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${receipt.receipt_id.replaceAll(":", "-")}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function render(rows) {
  const slot = $("human-receipt");
  if (!rows.length) {
    slot.innerHTML = `<div class="empty-state"><div class="glyph">H</div><div class="big">No human decision has been recorded yet.</div><div>Run an orange case, open <a href="/review">Needs me</a>, and decide it.</div></div>`;
    return;
  }

  slot.innerHTML = rows
    .map((r) => {
      const approved = r.human_review.outcome === "overridden";
      const summary = r.human_receipt || {};
      const reviewer = summary.reviewer || {
        name: r.human_review.reviewer_name || "Demo reviewer",
        role: r.human_review.reviewer_role || "Customer / approver",
      };
      const checks = r.check_results || [];
      const passCount = checks.filter((c) => c.outcome === "pass").length;
      const reviewCount = checks.filter((c) => c.outcome === "review").length;
      const failCount = checks.filter((c) => c.outcome === "fail").length;
      const findings = summary.important_findings || r.reason_codes || [];
      return `<article class="human-receipt-card ${personaClass(r.actor_ref)}" id="human-${esc(r.receipt_id)}">
        <div class="receipt-top">
          <div class="seal ${approved ? "approved" : "declined"}">${approved ? "✓" : "—"}</div>
          <div>
            <div class="eyebrow">SYSTEM-SEALED HUMAN DECISION RECEIPT</div>
            <h2>${esc(summary.headline || (approved ? "Approved once for this simulated transaction" : "Declined — leave the item unchanged"))}</h2>
            <p>${esc(r.product_name || r.subject_ref)}</p>
          </div>
        </div>

        <div class="receipt-status-grid human-receipt-status" data-human-status="${esc(r.receipt_id)}" aria-label="Human receipt status summary">
          <span><small>Receipt integrity</small><b data-human-integrity>Checking…</b></span>
          <span><small>Original decision</small><b>${esc(r.objective_posture)}</b></span>
          <span><small>Human outcome</small><b>${esc(approved ? "Approved once" : "Declined")}</b></span>
          <span><small>Transaction authority</small><b data-human-authority>Checking…</b></span>
        </div>

        <div class="human-receipt-grid">
          <section class="human-summary primary">
            <h3>What happened</h3>
            <p><strong>What RAMIFY found:</strong> ${esc(summary.what_ramify_found || `Objective posture ${r.objective_posture}.`)}</p>
            <p><strong>What the agent did:</strong> ${esc(summary.what_the_agent_did || `${r.actor_label} returned ${r.actor_decision} and asked a person.`)}</p>
            <p><strong>What the person decided:</strong> ${esc(summary.what_the_person_decided || r.human_review.outcome_label || r.human_review.outcome)}</p>
            <p><strong>What happens next:</strong> ${esc(summary.consequence || (approved ? "One simulated transaction may proceed using the authority recorded here." : "No simulated transaction is created from this review."))}</p>
          </section>

          <section class="human-summary">
            <h3>Who decided</h3>
            <dl class="receipt-fields compact">
              <dt>Name</dt><dd>${esc(reviewer.name)}</dd>
              <dt>Role</dt><dd>${esc(reviewer.role)}</dd>
              <dt>Scope</dt><dd>${esc(summary.scope || r.human_review.decision_scope || "this simulated transaction only")}</dd>
              <dt>Recorded</dt><dd class="mono">${esc(summary.reviewed_at || r.human_review.reviewed_at || r.timestamp)}</dd>
            </dl>
          </section>

          <section class="human-summary">
            <h3>What was checked</h3>
            <div class="human-check-counts">
              <span class="pill pill-pass">${passCount} passed</span>
              <span class="pill pill-review">${reviewCount} need attention</span>
              <span class="pill pill-fail">${failCount} failed</span>
            </div>
            <p><strong>Main reason:</strong> ${esc(summary.why_it_stopped || r.primary_reason || "No primary reason recorded.")}</p>
            <p><strong>Recorded findings:</strong> ${esc(findings.join(", ") || "none")}</p>
          </section>

          <section class="human-summary integrity">
            <h3>What did not change</h3>
            <p>The original machine receipt remains unchanged. This human receipt is a new linked record.</p>
            <dl class="receipt-fields compact">
              <dt>Original receipt</dt><dd class="mono">${esc(summary.original_receipt?.receipt_id || r.supersedes_receipt)}</dd>
              <dt>Original hash</dt><dd class="mono break">${esc(summary.original_receipt?.payload_hash || "Available in the original receipt")}</dd>
              <dt>Human receipt</dt><dd class="mono">${esc(r.receipt_id)}</dd>
              <dt>Human receipt hash</dt><dd class="mono break">${esc(r.payload_hash)}</dd>
            </dl>
          </section>
        </div>

        <p class="human-notice">${esc(summary.notice || "Plain-language summary of a signed synthetic demonstration record. No real purchase or approval occurred.")}</p>
        <details><summary>Full signed JSON record</summary><pre>${esc(JSON.stringify(r, null, 2))}</pre></details>
        <div class="queue-actions">
          <button class="btn btn-sm btn-ghost" data-verify="${esc(r.receipt_id)}">Verify this receipt</button>
          <button class="btn btn-sm btn-quiet" data-original="${esc(r.supersedes_receipt)}">Verify original machine receipt</button>
          <button class="btn btn-sm btn-quiet" data-download="${esc(r.receipt_id)}">Download JSON</button>
          <button class="btn btn-sm btn-quiet" data-print="${esc(r.receipt_id)}">Print</button>
          <a class="btn btn-sm btn-quiet" href="/activity">Open full activity</a>
        </div>
      </article>`;
    })
    .join("");

  rows.forEach((receipt) => void refreshHumanReceiptStatus(receipt));

  const byId = Object.fromEntries(rows.map((r) => [r.receipt_id, r]));
  $$('[data-verify]').forEach((b) =>
    b.addEventListener('click', async () => {
      const r = await api(`/api/v0/receipt/${b.dataset.verify}`);
      await verifyInto('terminal', r, false);
      $('terminal').scrollIntoView({ behavior: 'smooth' });
    })
  );
  $$('[data-original]').forEach((b) =>
    b.addEventListener('click', async () => {
      const r = await api(`/api/v0/receipt/${b.dataset.original}`);
      await verifyInto('terminal', r, false);
      $('terminal').scrollIntoView({ behavior: 'smooth' });
    })
  );
  $$('[data-download]').forEach((b) =>
    b.addEventListener('click', () => downloadReceipt(byId[b.dataset.download]))
  );
  $$('[data-print]').forEach((b) => b.addEventListener('click', () => window.print()));
}

async function refreshHumanReceiptStatus(receipt) {
  const root = document.querySelector(`[data-human-status="${CSS.escape(receipt.receipt_id)}"]`);
  if (!root) return;
  const integrity = root.querySelector("[data-human-integrity]");
  const authority = root.querySelector("[data-human-authority]");
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
      authority.textContent = "Not current / consumed";
      authority.className = "status-warn";
    }
  } catch {
    integrity.textContent = "Could not verify";
    authority.textContent = "Could not verify";
    integrity.className = authority.className = "status-warn";
  }
}

startPage(boot);

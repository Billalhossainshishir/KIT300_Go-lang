"use strict";

// The agent roster and its editor.
//
// The comparison table is the clearest evidence the architecture holds: many
// agents, one objective posture, many decisions. The banner above it asserts
// the objective column really was identical rather than asking for faith.
//
// The editor offers only inputs. Narrowing rules and permitted actions are
// derived server-side, so no field here can build an agent that buys something
// the checks stopped.

let agentData = null;
let editing = null;
let summaryIsCustom = false;

async function boot() {
  mountShell("/agents");
  mountFooter();
  const cat = await catalogue();

  $("product").innerHTML = cat.products
    .map((p) => `<option value="${esc(p.subject_ref)}">${esc(p.name)} — ${money(p.price_cents)}</option>`)
    .join("");

  $("run").addEventListener("click", compare);
  $("product").addEventListener("change", compare);
  $("qty").addEventListener("change", compare);
  $("new-agent").addEventListener("click", () => openEditor(null));
  $("editor-cancel").addEventListener("click", () => $("editor").close());
  $("editor-save").addEventListener("click", saveAgent);
  $("editor-reset").addEventListener("click", resetAgent);

  const preset = new URLSearchParams(location.search).get("subject");
  if (preset && cat.products.some((product) => product.subject_ref === preset)) {
    $("product").value = preset;
  }

  await loadAgents();
  compare();
}

async function loadAgents() {
  agentData = await api("/api/v0/agents");
  renderAgents();
}

// ── comparison ───────────────────────────────────────────────────────────

async function compare() {
  $("comparison").innerHTML = `<p class="placeholder">Asking every agent…</p>`;
  const result = await api("/api/v0/compare", {
    identifier: $("product").value,
    quantity: Number($("qty").value) || 1,
  });

  const rows = result.personas
    .map((p) => {
      const applied = p.applied_rules.length
        ? p.applied_rules
            .map(
              (r) =>
                `<span class="pill pill-${r.kind === "commercial" ? "info" : "review"}">${esc(
                  r.rule_id.replace(/_/g, " ")
                )}</span>`
            )
            .join(" ")
        : `<span style="color:var(--ink-4);">nothing applied</span>`;

      return `
      <tr class="persona-row ${personaClass(p.actor_ref)}">
        <td class="persona-name-cell">
          <strong><span class="persona-dot" aria-hidden="true"></span>${esc(p.actor_label)}</strong><br>
          <span style="font-size:12px;color:var(--ink-3);">${esc(p.summary)}</span>
          ${personaFingerprint(agentData?.agents.find((a) => a.ref === p.actor_ref))}
        </td>
        <td class="mono">${esc(p.objective_posture)}</td>
        <td>
          <span class="pill pill-${esc(p.traffic_light.colour)}">${esc(p.traffic_light.label)}</span>
          ${p.narrowed ? '<div class="narrowed-mark">↓ tightened</div>' : ""}
        </td>
        <td>
          ${esc(p.selected_action.replace(/_/g, " "))}
          ${p.unattended ? '<div style="font-size:11px;color:var(--green);font-weight:700;margin-top:4px;">no person involved</div>' : ""}
        </td>
        <td style="font-size:12px;">${applied}</td>
        <td><a class="btn btn-sm btn-ghost" href="/?subject=${encodeURIComponent(
          result.subject_ref
        )}&actor=${encodeURIComponent(p.actor_ref)}">Open</a></td>
      </tr>`;
    })
    .join("");

  const banner = result.objective_agreed
    ? `<div class="condition met" style="margin-bottom:15px;">
         <span class="mark">✓</span>
         <span>
           <span class="clabel">Every agent got the same answer about the product:
             <code>${esc(result.objective_posture)}</code></span>
           <div class="cdetail">The checks do not know who is asking. If this line ever said
             otherwise, the agents would be influencing the assessment and the whole design
             would be broken.</div>
         </span>
       </div>`
    : `<div class="condition unmet" style="margin-bottom:15px;">
         <span class="mark">!</span>
         <span><span class="clabel">The agents disagreed about the product itself</span>
         <div class="cdetail">This should be impossible.</div></span>
       </div>`;

  const priced =
    result.order && result.order.line_total_cents != null
      ? `<p style="font-size:13.5px;color:var(--ink-3);margin:0 0 14px;">
           ${esc(result.order.quantity)} × ${money(result.order.unit_price_cents)} =
           <strong>${money(result.order.line_total_cents)}</strong> per line</p>`
      : "";

  $("comparison").innerHTML = `
    <h3 style="font-family:var(--serif);font-weight:500;font-size:21px;margin:0 0 5px;">
      ${esc(result.product_name)}</h3>
    ${priced}
    ${banner}
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Agent</th><th>Answer about the product</th><th>What it means for them</th>
          <th>What it does</th><th>Its own rule</th><th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── roster ───────────────────────────────────────────────────────────────

function renderAgents() {
  $("personas").innerHTML = agentData.agents
    .map((p) => {
      const rules = [["Buying", p.autonomy_label]];
      if (p.budget_limit_cents != null) rules.push(["Ceiling", `${money(p.budget_limit_cents)} per line`]);
      if (p.brand_allowlist && p.brand_allowlist.length) rules.push(["Brands", p.brand_allowlist.join(", ")]);
      if (p.approved_vendors && p.approved_vendors.length) {
        rules.push(["Sellers", `${p.approved_vendors.length} approved`]);
      }
      if (p.warned_outcome_requires_review) rules.push(["Warnings", "always come to me"]);

      return `
      <div class="persona ${personaClass(p.ref)}" data-open="${esc(p.ref)}" tabindex="0" role="button"
           aria-label="Edit ${esc(p.label)}">
        <span class="edit-hint">click to edit ✎</span>
        <span class="autonomy-badge autonomy-${esc(p.autonomy)}">${esc(
          p.autonomy.replace(/_/g, " ")
        )}</span>
        <h3>${esc(p.label)}${p.edited ? '<span class="edited-badge">edited</span>' : ""}</h3>
        <p class="summary">${esc(p.summary)}</p>
        <p class="desc">${esc(p.description)}</p>
        ${personaFingerprint(p)}
        <ul class="rules">
          ${rules.map(([k, v]) => `<li><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></li>`).join("")}
        </ul>
        <footer>
          <button class="btn btn-sm" data-edit="${esc(p.ref)}">Edit what it may do</button>
          ${
            p.edited
              ? `<button class="btn btn-sm btn-quiet" data-reset="${esc(p.ref)}">${
                  p.built_in ? "Reset" : "Delete"
                }</button>`
              : ""
          }
        </footer>
      </div>`;
    })
    .join("");

  $$("[data-edit]").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      openEditor(b.dataset.edit);
    })
  );
  $$("[data-reset]").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      resetAgent(b.dataset.reset);
    })
  );
  // The whole card is the target — editing is the point of this page.
  $$("[data-open]").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (!e.target.closest("button")) openEditor(card.dataset.open);
    });
    card.addEventListener("keydown", (e) => {
      if (e.target.closest("button, a, input, select, textarea")) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openEditor(card.dataset.open);
      }
    });
  });
}

// ── editor ───────────────────────────────────────────────────────────────

function openEditor(ref) {
  editing = ref ? agentData.agents.find((a) => a.ref === ref) : null;
  const blank = {
    ref: null,
    label: "",
    summary: "",
    description: "",
    autonomy_level: "none",
    purchase_style: "cart",
    budget_limit_cents: null,
    brand_allowlist: null,
    approved_vendors: null,
    warned_outcome_requires_review: false,
    edited: false,
    built_in: false,
  };
  const a = editing || blank;

  $("editor-title").textContent = editing ? `Edit ${a.label}` : "New agent";
  $("f-label").value = a.label;
  $("f-summary").value = a.summary;
  $("f-budget").value = a.budget_limit_cents == null ? "" : a.budget_limit_cents / 100;
  $("f-purchase-style").value = a.purchase_style || "cart";
  $("f-warned").checked = !!a.warned_outcome_requires_review;

  $("f-autonomy").innerHTML = agentData.autonomy_levels
    .map((l) => `<option value="${esc(l.value)}">${esc(l.label)}</option>`)
    .join("");
  $("f-autonomy").value = a.autonomy_level || "none";

  $("f-brands").innerHTML = agentData.brands
    .map(
      (brand) =>
        `<button type="button" class="chip" data-brand="${esc(brand)}"
           aria-pressed="${(a.brand_allowlist || []).includes(brand)}">${esc(brand)}</button>`
    )
    .join("");
  $("f-vendors").innerHTML = agentData.sellers
    .map(
      (s) =>
        `<button type="button" class="chip" data-vendor="${esc(s.ref)}"
           aria-pressed="${(a.approved_vendors || []).includes(s.ref)}">${esc(s.name)}</button>`
    )
    .join("");

  // The summary tracks the settings until somebody writes their own. A card
  // advertising last week's spending limit is worse than no summary.
  summaryIsCustom = !!(a.summary && a.summary !== a.derived_summary);

  $$("#editor .chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") !== "true");
      refreshPreview();
    })
  );
  ["f-label", "f-budget", "f-autonomy", "f-warned"].forEach((id) =>
    $(id).addEventListener("input", refreshPreview)
  );
  $("f-purchase-style").addEventListener("input", () => {
    syncTransactionControls();
    refreshPreview();
  });
  $("f-summary").addEventListener("input", () => {
    summaryIsCustom = true;
  });

  $("editor-reset").hidden = !(editing && editing.edited);
  $("editor-error").textContent = "";
  syncTransactionControls();
  refreshPreview();
  $("editor").showModal();
}

function syncTransactionControls() {
  const requisition = $("f-purchase-style").value === "requisition";
  if (requisition) $("f-autonomy").value = "none";
  $("f-autonomy").disabled = requisition;
  $("autonomy-hint").textContent = requisition
    ? "Procurement mode creates a signed requisition; it does not perform autonomous consumer checkout."
    : "";
}

// Mirrors the server's wording so the field before saving matches the card
// after it.
function describeAgent(f) {
  const parts = [
    f.purchase_style === "requisition"
      ? "stages procurement requisitions"
      : f.autonomy_level === "clean_or_warned"
        ? "buys unattended, warnings and all"
        : f.autonomy_level === "clean_only"
          ? "buys unattended on a clean result"
          : "always asks first",
  ];
  if (f.budget_limit_cents != null) parts.push(`up to ${money(f.budget_limit_cents).replace(".00", "")} a line`);
  if (f.brand_allowlist) parts.push(`${f.brand_allowlist.length} brand${f.brand_allowlist.length > 1 ? "s" : ""} only`);
  if (f.approved_vendors) {
    parts.push(`${f.approved_vendors.length} approved seller${f.approved_vendors.length > 1 ? "s" : ""}`);
  }
  if (f.purchase_style !== "requisition") parts.push("uses the consumer basket");
  const summary = parts.join(", ");
  return summary.charAt(0).toUpperCase() + summary.slice(1);
}

function readForm() {
  const dollars = $("f-budget").value.trim();
  const brands = $$("#f-brands .chip[aria-pressed='true']").map((c) => c.dataset.brand);
  const vendors = $$("#f-vendors .chip[aria-pressed='true']").map((c) => c.dataset.vendor);
  return {
    label: $("f-label").value.trim(),
    summary: $("f-summary").value.trim(),
    description: (editing && editing.description) || $("f-summary").value.trim(),
    autonomy_level: $("f-autonomy").value,
    purchase_style: $("f-purchase-style").value || "cart",
    budget_limit_cents: dollars === "" ? null : Math.round(Number(dollars) * 100),
    brand_allowlist: brands.length ? brands : null,
    approved_vendors: vendors.length ? vendors : null,
    warned_outcome_requires_review: $("f-warned").checked,
  };
}

// Shows an edit's effect before saving, so nobody guesses from a label.
async function refreshPreview() {
  const fields = readForm();

  if (!summaryIsCustom) {
    $("f-summary").value = describeAgent(fields);
    fields.summary = $("f-summary").value;
  }
  const hint = agentData.autonomy_levels.find((l) => l.value === fields.autonomy_level);
  $("autonomy-hint").textContent = fields.purchase_style === "requisition"
    ? "Procurement mode creates a signed requisition; it does not perform autonomous consumer checkout."
    : fields.autonomy_level === "clean_or_warned"
      ? "It will buy even when a finding is attached. It still cannot buy anything the checks stopped."
      : hint
        ? hint.label
        : "";

  if (!fields.label) {
    $("preview").innerHTML = `<p class="placeholder">Give the agent a name to see what it would do.</p>`;
    return;
  }

  try {
    const compiled = await api("/api/v0/agents/preview", fields);
    const rows = ["allow", "allow_with_warning", "hold", "escalate", "block"]
      .map((posture) => {
        const actions = compiled.permitted_actions[posture] || [];
        const transactionAvailable = actions.some((a) =>
          ["purchase_autonomously", "add_to_mock_cart", "create_mock_requisition"].includes(a)
        );
        return `
        <div class="check" style="grid-template-columns:150px 1fr;padding:6px 0;">
          <span class="clabel" style="font-family:var(--mono);font-size:12px;">${esc(posture)}</span>
          <span class="cdetail">${esc(actions.map((a) => a.replace(/_/g, " ")).join(", "))}
            ${transactionAvailable ? "" : '<span style="color:var(--ink-4);"> — no transaction action</span>'}</span>
        </div>`;
      })
      .join("");
    $("preview").innerHTML = rows;
    $("editor-error").textContent = "";
  } catch (error) {
    $("editor-error").textContent = error.message;
  }
}

async function saveAgent() {
  const fields = readForm();
  const button = $("editor-save");
  button.disabled = true;
  try {
    if (editing) {
      await api(`/api/v0/agents/${editing.ref}`, fields, "PUT");
      toast(`${fields.label} updated.`, "good");
    } else {
      await api("/api/v0/agents", fields);
      toast(`${fields.label} created.`, "good");
    }
    $("editor").close();
    await catalogue(true);
    await loadAgents();
    compare();
  } catch (error) {
    $("editor-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function resetAgent(ref) {
  const target = ref || (editing && editing.ref);
  if (!target) return;
  const result = await api(`/api/v0/agents/${target}`, null, "DELETE");
  $("editor").close();
  toast(result.deleted ? "Agent deleted." : "Reset to its shipped settings.");
  await catalogue(true);
  await loadAgents();
  compare();
}

startPage(boot);

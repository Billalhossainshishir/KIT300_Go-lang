"use strict";

// The basket, and the order record checkout produces.
//
// The record is the point: signed the same way a receipt is, verified by the
// same tool, and naming the receipt behind every line.

async function boot() {
  mountShell("/cart");
  mountFooter();
  await load();
}

async function load() {
  const basket = await api("/api/v0/cart");
  setBadge("cart-count", basket.item_count);
  renderBasket(basket);
  renderRequisitions(basket.requisitions || []);
  renderPastOrders(basket.orders);
}

function renderBasket(basket) {
  if (!basket.lines.length) {
    $("basket").innerHTML = `
      <div class="empty-state">
        <div class="glyph">◇</div>
        <div class="big">Nothing in the basket yet.</div>
        <div>When a signed agent decision permits a cart purchase, the checked item can be staged here. Procurement-only decisions create a separate requisition below.</div>
        <div style="margin-top:20px;"><a class="btn" href="/shop">Go shopping</a></div>
      </div>`;
    return;
  }

  const justAdded = sessionStorage.getItem("ramify:just-added");
  sessionStorage.removeItem("ramify:just-added");

  const lines = basket.lines
    .map(
      (line) => `
      <div class="cart-line${line.line_id === justAdded ? " just-added" : ""} ${personaClass(line.actor_ref)}"
           id="line-${esc(line.line_id)}">
        <div>
          <div class="cname">${esc(line.product_name)}</div>
          <div class="cmeta">
            ${esc(line.brand)} · ${esc(line.quantity)} × ${money(line.unit_price_cents)} ·
            checked for <span class="persona-inline ${personaClass(line.actor_ref)}"><span class="persona-dot" aria-hidden="true"></span>${esc(line.actor_label)}</span>
            ${
              line.unattended
                ? '<span class="pill pill-green" style="margin-left:7px;">bought unattended</span>'
                : line.human_authorised
                  ? '<span class="pill pill-orange" style="margin-left:7px;">human authorised</span>'
                  : ""
            }
          </div>
          <div class="creceipt">
            receipt ${esc(line.receipt_ref)}<br>
            ${esc(line.payload_hash)}
            ${
              line.human_authorised
                ? `<br><a href="/human-receipt?receipt=${encodeURIComponent(line.receipt_ref)}">Open the linked human receipt</a>`
                : ""
            }
          </div>
        </div>
        <div class="cright">
          <div class="cprice">${money(line.line_total_cents)}</div>
          <div style="display:flex;gap:8px;">
            <button class="btn btn-sm btn-ghost" data-verify="${esc(line.receipt_ref)}">Check it</button>
            <button class="btn btn-sm btn-quiet" data-remove="${esc(line.line_id)}">Remove</button>
          </div>
        </div>
      </div>`
    )
    .join("");

  $("basket").innerHTML = `
    ${lines}
    <div class="cart-total">
      <div>
        <div class="amount">${money(basket.total_cents)}</div>
        <div class="sub">${basket.line_count} line${basket.line_count > 1 ? "s" : ""} ·
          ${basket.item_count} item${basket.item_count > 1 ? "s" : ""} ·
          every one with a receipt behind it</div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <button class="btn btn-ghost" id="clear">Empty the basket</button>
        <button class="btn btn-go btn-lg" id="checkout">Place the order</button>
      </div>
    </div>
    <p class="caveat">Nothing is bought. Placing the order seals a record of what was checked and
      what was decided, and empties the basket.</p>`;

  $$("[data-remove]").forEach((b) =>
    b.addEventListener("click", () => removeLine(b.dataset.remove))
  );
  $$("[data-verify]").forEach((b) =>
    b.addEventListener("click", async () => {
      const receipt = await api(`/api/v0/receipt/${b.dataset.verify}`);
      await verifyInto("terminal", receipt, false);
      $("terminal").scrollIntoView({ block: "nearest", behavior: "smooth" });
    })
  );
  $("clear").addEventListener("click", async () => {
    await api("/api/v0/cart", null, "DELETE");
    toast("Basket emptied.");
    load();
  });
  $("checkout").addEventListener("click", checkout);

  const highlighted = $$(".cart-line.just-added")[0];
  if (highlighted) {
    highlighted.scrollIntoView({ block: "center", behavior: "smooth" });
    setTimeout(() => highlighted.classList.remove("just-added"), 2600);
  }
}

async function removeLine(lineId) {
  const card = $(`line-${lineId}`);
  if (card) card.classList.add("removing");
  await api(`/api/v0/cart/line/${lineId}`, null, "DELETE");
  setTimeout(load, 420);
}

let justPlacedId = null;

async function checkout() {
  const button = $("checkout");
  button.disabled = true;
  button.textContent = "Sealing the record…";
  try {
    const result = await api("/api/v0/cart/checkout", {});
    justPlacedId = result.order.order_id;
    toast("Order record created. Every line is linked to the receipt that allowed it.", "good");
    await load();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (error) {
    button.disabled = false;
    button.textContent = "Place the order";
    toast(error.message, "bad");
  }
}

function renderRequisitions(requisitions) {
  let container = $("requisitions");
  if (!container) {
    container = document.createElement("section");
    container.id = "requisitions";
    $("terminal").insertAdjacentElement("afterend", container);
  }
  if (!requisitions.length) {
    container.innerHTML = "";
    return;
  }
  const freshId = sessionStorage.getItem("ramify:just-requisitioned");
  sessionStorage.removeItem("ramify:just-requisitioned");
  container.innerHTML = `<h2 class="section">Procurement requisitions</h2><p class="section-hint">These are separate from the consumer basket. Each is a signed, simulated procurement record.</p>${requisitions.map((req) => `
    <article class="order-record ${req.requisition_id === freshId ? "just-added" : ""}">
      <div class="eyebrow">SIMULATED REQUISITION</div>
      <h3>${esc(req.product_name)} · ${money(req.line_total_cents)}</h3>
      <p>${esc(req.customer_summary?.headline || "RAMIFY recorded a purchase requisition.")}</p>
      <div class="queue-meta">${esc(req.actor_label)} · ${esc(req.requisition_id)}<br>authority: ${esc(req.receipt_ref)}</div>
      <details class="detail-technical" style="margin:14px 0;"><summary>Full signed requisition JSON</summary><pre>${esc(JSON.stringify(req, null, 2))}</pre></details>
      <button class="btn btn-sm btn-ghost" data-verify-requisition="${esc(req.requisition_id)}">Check this record</button>
    </article>`).join("")}`;
  $$("[data-verify-requisition]", container).forEach((button) => button.addEventListener("click", async () => {
    const req = requisitions.find((item) => item.requisition_id === button.dataset.verifyRequisition);
    if (req) {
      await verifyInto("terminal", req, false);
      $("terminal").scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }));
}

function orderCard(order, fresh) {
  const lines = order.lines
    .map(
      (line) => `
      <tr>
        <td>${esc(line.product_name)}</td>
        <td class="mono">${esc(line.quantity)}</td>
        <td class="mono">${money(line.line_total_cents)}</td>
        <td class="mono">${esc(line.objective_posture)} → ${esc(line.actor_decision)}</td>
        <td class="mono" style="font-size:10.5px;">${esc(line.receipt_ref.slice(-14))}</td>
      </tr>`
    )
    .join("");

  const humanCount = order.lines.filter((line) => line.human_authorised).length;
  const summary = order.customer_summary || {};
  const plainSummary = summary.headline ||
    (humanCount
      ? `RAMIFY checked every line, kept the original machine decisions unchanged, and recorded ${humanCount} human-authorised line${humanCount === 1 ? "" : "s"} as linked follow-on receipts.`
      : `RAMIFY checked every line, confirmed that each selected agent was permitted to proceed, and attached the supporting signed receipt to the order.`);

  return `
    <div class="order-record">
      <h3>${fresh ? "Order placed" : "Order"} · ${money(order.total_cents)}</h3>
      <div class="checkout-human-receipt">
        <div class="eyebrow">CUSTOMER RECEIPT SUMMARY</div>
        <strong>What RAMIFY did</strong>
        <p>${esc(plainSummary)}</p>
        ${summary.what_was_checked ? `<p><strong>What was checked:</strong> ${esc(summary.what_was_checked)}</p>` : ""}
        ${summary.how_the_order_was_authorised ? `<p><strong>How it was authorised:</strong> ${esc(summary.how_the_order_was_authorised)}</p>` : ""}
        ${summary.audit_message ? `<p><strong>Audit trail:</strong> ${esc(summary.audit_message)}</p>` : ""}
        <p class="detail-note">This plain-language summary is part of the signed order record. The full JSON remains available below.</p>
      </div>
      <p style="font-size:13.5px;color:var(--ink-2);margin:16px 0;max-width:72ch;">
        ${esc(order.notice)}
      </p>
      <div class="table-wrap" style="margin-bottom:15px;">
        <table>
          <thead><tr><th>Item</th><th>Qty</th><th>Total</th><th>Outcome</th><th>Receipt</th></tr></thead>
          <tbody>${lines}</tbody>
        </table>
      </div>
      <div class="queue-meta">${esc(order.order_id)}<br>${esc(order.payload_hash)}</div>
      <details class="detail-technical" style="margin:14px 0;">
        <summary>Full signed order JSON</summary>
        <pre>${esc(JSON.stringify(order, null, 2))}</pre>
      </details>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <button class="btn btn-sm btn-ghost" data-verify-order="${esc(order.order_id)}">Check this record</button>
        <a class="btn btn-sm btn-quiet" href="/activity">See everything that happened →</a>
      </div>
    </div>`;
}

// One list, newest first. The order just placed is marked rather than drawn
// twice.
function renderPastOrders(orders) {
  const container = $("past-orders");
  if (!orders || !orders.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML =
    `<h2 class="section">Orders you have placed</h2>` +
    orders.map((order) => orderCard(order, order.order_id === justPlacedId)).join("");

  $$("[data-verify-order]").forEach((b) =>
    b.addEventListener("click", async () => {
      const record = orders.find((o) => o.order_id === b.dataset.verifyOrder);
      if (record) {
        await verifyInto("terminal", record, false);
        $("terminal").scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    })
  );
}

startPage(boot);

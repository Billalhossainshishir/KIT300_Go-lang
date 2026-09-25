"use strict";

async function boot() {
  mountShell("/technical");
  mountFooter();

  const [health, vocab, coverage, ledger, agent] = await Promise.all([
    api("/healthz"),
    api("/api/v0/vocabulary"),
    api("/api/v0/demo/coverage"),
    api("/api/v0/ledger/verify"),
    api("/api/v0/agent/status"),
  ]);

  $("technical-kpis").innerHTML = [
    ["Products", coverage.product_count],
    ["Scenarios", coverage.scenario_count],
    ["Agents", coverage.actor_count],
    ["Evidence records", coverage.evidence_count],
    ["Ledger receipts", ledger.total],
    ["Build", health.build],
  ]
    .map(([label, value]) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`)
    .join("");

  const environment = $("environment-proof");
  if (environment) {
    const modeLabel = agent.local_model_available
      ? `${agent.framework || "Native Go adapter"} + ${agent.provider || "Ollama"} + ${agent.model || "local model"}`
      : agent.presentation_state === "model_missing"
      ? "Model not installed - deterministic fallback"
      : agent.presentation_state === "offline"
      ? "Ollama offline - deterministic fallback"
      : "Deterministic fallback available";
    environment.innerHTML = `<div class="environment-proof-grid">
      <span><small>Server endpoint</small><b>${esc(health.configured_endpoint || "127.0.0.1:8000")}</b></span>
      <span><small>Frontend assets</small><b>served from local project folder</b></span>
      <span><small>Core web calls</small><b>${health.core_external_network_calls ? "external calls configured" : "none configured"}</b></span>
      <span><small>AI endpoint</small><b>local Ollama when available</b></span>
      <span><small>Current interpretation path</small><b>${esc(modeLabel)}</b></span>
      <span><small>Decision authority</small><b>deterministic RAMIFY core</b></span>
    </div><p class="detail-note">This is configuration evidence from the local server, not a network-forensics audit. The shipped Go launcher binds the local server to 127.0.0.1 by default and the core RAMIFY decision path has no external web dependency.</p>`;
  }

  const ready = Boolean(agent.local_model_available) && agent.active_mode === "local_llm";
  const aiState = ready ? "LIVE LOCAL LLM AVAILABLE" : "SAFE FALLBACK";
  const aiDetail = ready
    ? `${agent.framework} orchestrates ${agent.provider} with ${agent.model} on the local machine.`
    : agent.presentation_detail || agent.detail || "The optional local model is unavailable or slow; deterministic interpretation remains active.";
  $("local-ai-runtime").innerHTML = `
    <div class="local-ai-status ${ready ? "ready" : "fallback"}">
      <div class="local-ai-orb" aria-hidden="true"></div>
      <div>
        <span class="eyebrow">${esc(aiState)}</span>
        <h3>${ready ? `${esc(agent.framework)} + ${esc(agent.provider)} + ${esc(agent.model)}` : "Deterministic fallback is active"}</h3>
        <p>${esc(aiDetail)}</p>
      </div>
      <div class="local-ai-facts">
        <span><small>Interpretation</small><b>${esc(agent.interpretation_path)}</b></span>
        <span><small>Decision authority</small><b>Deterministic RAMIFY engine only</b></span>
        <span><small>Explanation</small><b>${ready ? "Local LLM, presentation only" : "Receipt-derived deterministic summary"}</b></span>
      </div>
    </div>
    <p class="detail-note">The language model never writes the objective posture, reason codes, permitted action, human review outcome or purchase authority. Those remain deterministic and receipt-backed.</p>`;

  const transitionRows = vocab.transitions.order_least_to_most_restrictive
    .map((objective) => {
      const allowed = vocab.transitions.rows
        .filter((row) => row.objective_posture === objective && row.permitted)
        .map((row) => row.actor_decision);
      return `<tr><td class="mono">${esc(objective)}</td><td class="mono">${esc(allowed.join(", "))}</td></tr>`;
    })
    .join("");

  $("transitions").innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Objective posture</th><th>Agent may remain or narrow to</th></tr></thead>
        <tbody>${transitionRows}</tbody>
      </table>
    </div>
    <p class="detail-note">An agent may narrow the objective result. It may never widen it.</p>`;

  $("coverage").innerHTML = `<div class="coverage-grid">${coverage.scenarios
    .map(
      (scenario) => `<div>
        <strong>${esc(scenario.id)}</strong>
        <span>${esc(scenario.note)}</span>
        <small>${esc(scenario.expected_objective)} → ${esc(scenario.expected_decision)}</small>
      </div>`
    )
    .join("")}</div>`;

  if (!ledger.total) {
    $("ledger").innerHTML = `
      <div class="empty-state">
        <div class="glyph">◇</div>
        <div class="big">No receipts yet.</div>
        <div>Run a product check to create the first signed record.</div>
      </div>`;
    return;
  }

  const freshness = ledger.past_freshness_window
    ? `${ledger.past_freshness_window} historical record(s) are past the one-hour purchase window; their seals can still be intact.`
    : "Every receipt is still inside its one-hour purchase window.";
  const integrity = ledger.invalid
    ? `${ledger.invalid} record(s) have an integrity problem and require attention.`
    : "Every stored record still matches its SHA-256 hash and Ed25519 signature.";

  $("ledger").innerHTML = `
    <div class="ledger-health ${ledger.all_valid ? "ok" : "bad"}">
      <strong>${ledger.intact}/${ledger.total} records cryptographically intact</strong>
      <span>${esc(integrity)}</span>
      <span>${esc(freshness)}</span>
    </div>`;
}

startPage(boot);

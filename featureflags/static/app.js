// Dashboard: every control below calls the real control-plane API.
const API_KEY = "demo-api-key-12345"; // documented demo key, not a secret
const headers = {"x-api-key": API_KEY, "Content-Type": "application/json", "x-actor": "dashboard"};

async function api(path, options = {}) {
  const res = await fetch(path, {headers, ...options});
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function loadHealth() {
  const h = await fetch("/health").then(r => r.json());
  document.getElementById("health").textContent = `status: ${h.status} · config v${h.config_version}`;
}

async function toggleFlag(key, enabled) {
  await api(`/v1/flags/${key}`, {method: "PATCH", body: JSON.stringify({enabled})});
  loadFlags(); loadAudit();
}

async function setRollout(key, pct) {
  await api(`/v1/flags/${key}`, {method: "PATCH", body: JSON.stringify({fallthrough_percentage: Number(pct)})});
  loadFlags(); loadAudit();
}

async function requestRisk(key) {
  const out = document.getElementById("risk");
  out.textContent = "Asking the risk agent...";
  try {
    const proposal = await api("/v1/risk/proposals", {method: "POST", body: JSON.stringify({flag_key: key})});
    const r = proposal.recommendation;
    out.innerHTML = `<div class="card"><h3>${key}: ${r.action}</h3>
      <p class="muted">Confidence ${(r.confidence * 100).toFixed(0)}% · suggested ${r.suggested_percentage ?? "-"}%</p>
      <p>${r.reasons.join("<br>")}</p>
      <p class="muted">Proposal <code>${proposal.id}</code> is PENDING. Approving needs its token:</p>
      <button class="primary" onclick="approveProposal('${proposal.id}','${proposal.approval_token}')">Approve proposal</button></div>`;
  } catch (e) { out.textContent = `Risk agent: ${e.message} (ingest metrics first)`; }
}

async function approveProposal(id, token) {
  await api(`/v1/risk/proposals/${id}/approve`, {method: "POST",
    body: JSON.stringify({approver: "dashboard-user", approval_token: token})});
  document.getElementById("risk").textContent = "Proposal approved and executed. Flag + audit log updated.";
  loadFlags(); loadAudit();
}

async function loadFlags() {
  const {flags} = await api("/v1/flags");
  document.getElementById("flags").innerHTML = flags.map(f => `
    <article class="card">
      <div class="row" style="margin-top:0"><h3>${f.key}</h3>
        <span class="badge ${f.enabled ? "" : "off"}">${f.enabled ? "enabled" : "kill-switched"}</span></div>
      <p class="muted">${f.description || ""}</p>
      <div class="row"><span>Rollout <strong>${f.fallthrough_percentage}%</strong></span>
        <span class="muted">version ${f.version}</span></div>
      <div class="bar"><div style="width:${f.fallthrough_percentage}%"></div></div>
      <div class="row">
        <input type="range" min="0" max="100" step="5" value="${f.fallthrough_percentage}"
               onchange="setRollout('${f.key}', this.value)" aria-label="rollout percentage">
        <button class="${f.enabled ? "danger" : "primary"}" onclick="toggleFlag('${f.key}', ${!f.enabled})">
          ${f.enabled ? "Kill switch" : "Re-enable"}</button>
      </div>
      <div class="row"><button onclick="requestRisk('${f.key}')">Ask risk agent</button></div>
    </article>`).join("");
}

async function loadAudit() {
  const {audit} = await api("/v1/audit");
  document.getElementById("audit").innerHTML = audit.slice().reverse().slice(0, 20)
    .map(a => `<div><code>${new Date(a.timestamp * 1000).toLocaleTimeString()}</code>
      <strong>${a.action}</strong> ${a.flag_key} · v${a.version} · by ${a.actor}</div>`).join("")
      || "<p class='muted'>No audit entries yet.</p>";
}

document.getElementById("refresh-audit").addEventListener("click", loadAudit);
loadHealth(); loadFlags(); loadAudit();

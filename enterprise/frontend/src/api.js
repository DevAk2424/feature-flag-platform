// Service endpoints (microservices, not a monolith API):
//  - streaming gateway (SSE config stream + last-known-good snapshot)
//  - control plane (flag commands: rollout / kill switch)
//  - ai-risk-service (recommendations + guarded proposals)
export const GATEWAY = import.meta.env.VITE_GATEWAY_URL || 'http://localhost:8081'
export const CONTROL_PLANE = import.meta.env.VITE_CONTROL_PLANE_URL || 'http://localhost:8080'
export const AI_SERVICE = import.meta.env.VITE_AI_URL || 'http://localhost:8090'

export async function setRollout(key, percentage) {
  const r = await fetch(`${CONTROL_PLANE}/api/flags/${encodeURIComponent(key)}/rollout`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ percentage, actor: 'dashboard' }),
  })
  if (!r.ok) throw new Error(`rollout failed: ${r.status}`)
  return r.json()
}
export async function setKillSwitch(key, engage) {
  const r = await fetch(`${CONTROL_PLANE}/api/flags/${encodeURIComponent(key)}/${engage ? 'kill-switch' : 'enable'}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: engage, actor: 'dashboard' }),
  })
  if (!r.ok) throw new Error(`kill switch failed: ${r.status}`)
  return r.json()
}
export async function fetchAudit() {
  const r = await fetch(`${CONTROL_PLANE}/api/audit`)
  if (!r.ok) throw new Error(`audit failed: ${r.status}`)
  return r.json()
}
export async function getRecommendation(flagKey) {
  const r = await fetch(`${AI_SERVICE}/flags/${encodeURIComponent(flagKey)}/recommendation`)
  if (!r.ok) throw new Error(`recommendation failed: ${r.status}`)
  return r.json()
}
export async function createProposal(flagKey, metrics) {
  const r = await fetch(`${AI_SERVICE}/proposals`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ flag_key: flagKey, metrics }),
  })
  if (!r.ok) throw new Error(`proposal failed: ${r.status}`)
  return r.json()
}
export async function approveProposal(id, approver, token) {
  const r = await fetch(`${AI_SERVICE}/proposals/${id}/approve`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approver, approval_token: token }),
  })
  if (!r.ok) throw new Error(`approve failed: ${r.status}`)
  return r.json()
}
export async function rejectProposal(id, approver) {
  const r = await fetch(`${AI_SERVICE}/proposals/${id}/reject`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approver }),
  })
  if (!r.ok) throw new Error(`reject failed: ${r.status}`)
  return r.json()
}

// Pure helpers (unit-tested). The dashboard is a streaming client: config
// arrives as SSE snapshot + delta events from the streaming gateway.
export function applyDelta(flags, event) {
  if (!event || !event.flag) return flags
  const next = flags.filter(f => f.key !== event.flagKey)
  next.push(event.flag)
  return next.sort((a, b) => a.key.localeCompare(b.key))
}
export function mergeSnapshot(current, snapshot) {
  if (!snapshot || !Array.isArray(snapshot.flags)) return current
  return [...snapshot.flags].sort((a, b) => a.key.localeCompare(b.key))
}
export function rolloutLabel(flag) {
  if (!flag.enabled) return 'Kill switch ON'
  return `${flag.fallthroughPercentage}% rollout`
}
export function riskTone(action) {
  if (action === 'ROLLBACK') return 'danger'
  if (action === 'HOLD') return 'warning'
  if (action === 'CONTINUE_ROLLOUT') return 'ok'
  return 'neutral'
}
export function clampRollout(v) {
  const n = Number(v)
  if (Number.isNaN(n)) return 0
  return Math.min(100, Math.max(0, n))
}

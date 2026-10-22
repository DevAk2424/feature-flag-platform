import React, { useEffect, useRef, useState } from 'react'
import { GATEWAY, setRollout, setKillSwitch, fetchAudit, getRecommendation, createProposal, approveProposal, rejectProposal } from './api'
import { applyDelta, mergeSnapshot, rolloutLabel, riskTone, clampRollout } from './utils'

// Clean inline SVG line icons only - no emoji UI (project design rule).
const Icon = ({ d }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
)
const ICONS = {
  flag: 'M4 21V4m0 1h13l-2.5 4L17 13H4',
  bolt: 'M13 2L4 14h6l-1 8 9-12h-6l1-8z',
  shield: 'M12 3l7 3v5c0 5-3.5 8-7 10-3.5-2-7-5-7-10V6l7-3z',
  chart: 'M4 20V10m6 10V4m6 16v-7m4 7H2',
}

function FlagCard({ flag, onRollout, onKill }) {
  const [pct, setPct] = useState(flag.fallthroughPercentage)
  useEffect(() => setPct(flag.fallthroughPercentage), [flag.fallthroughPercentage, flag.version])
  return (
    <article className="card">
      <header>
        <span className="icon"><Icon d={ICONS.flag} /></span>
        <div>
          <h3>{flag.key}</h3>
          <p className="muted">{flag.description || '—'} · v{flag.version} · {flag.environment}</p>
        </div>
        <span className={flag.enabled ? 'badge on' : 'badge off'}>{rolloutLabel(flag)}</span>
      </header>
      <label className="slider-row">
        <span>Rollout {clampRollout(pct)}%</span>
        <input type="range" min="0" max="100" value={pct} disabled={!flag.enabled}
          onChange={e => setPct(e.target.value)} onMouseUp={() => onRollout(flag.key, clampRollout(pct))} onTouchEnd={() => onRollout(flag.key, clampRollout(pct))} />
      </label>
      <div className="row">
        <button className={flag.enabled ? 'danger' : 'ok'} onClick={() => onKill(flag.key, flag.enabled)}>
          {flag.enabled ? 'Engage kill switch' : 'Re-enable flag'}
        </button>
      </div>
    </article>
  )
}

function RiskPanel({ flags }) {
  const [selected, setSelected] = useState('')
  const [rec, setRec] = useState(null)
  const [proposal, setProposal] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { if (!selected && flags.length) setSelected(flags[0].key) }, [flags, selected])
  async function analyze() {
    setMsg('')
    try { setRec(await getRecommendation(selected)) } catch (e) { setMsg(String(e.message || e)) }
  }
  async function propose() {
    // Demo metrics payload: the panel asks the AI service for a guarded proposal.
    const metrics = { sample_size: 5000, error_rate: 0.011, baseline_error_rate: 0.010,
      latency_p95_ms: 212, baseline_latency_p95_ms: 200, success_rate: 0.99, baseline_success_rate: 0.99,
      current_rollout_percentage: flags.find(f => f.key === selected)?.fallthroughPercentage || 0 }
    try { const p = await createProposal(selected, metrics); setProposal(p); setRec(p.recommendation) }
    catch (e) { setMsg(String(e.message || e)) }
  }
  async function approve() {
    try { await approveProposal(proposal.id, 'dashboard-user', proposal.approval_token); setMsg('Approved — command event sent to the control plane. Watch the flag update live.'); setProposal(null) }
    catch (e) { setMsg(String(e.message || e)) }
  }
  async function reject() {
    try { await rejectProposal(proposal.id, 'dashboard-user'); setMsg('Proposal rejected. Nothing was changed.'); setProposal(null) }
    catch (e) { setMsg(String(e.message || e)) }
  }
  return (
    <section className="card wide">
      <header><span className="icon"><Icon d={ICONS.shield} /></span><h3>AI release-risk agent</h3></header>
      <div className="row">
        <select value={selected} onChange={e => setSelected(e.target.value)}>
          {flags.map(f => <option key={f.key} value={f.key}>{f.key}</option>)}
        </select>
        <button onClick={analyze}>Analyze metrics</button>
        <button onClick={propose}>Create guarded proposal</button>
      </div>
      {rec && <div className={`risk ${riskTone(rec.action)}`}>
        <strong>{rec.action}</strong> · confidence {(rec.confidence * 100).toFixed(0)}%
        {rec.suggested_percentage != null && <> · suggested rollout {rec.suggested_percentage}%</>}
        <ul>{(rec.reasons || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
      </div>}
      {proposal && proposal.status === 'PENDING' && <div className="row">
        <span className="muted">Proposal {proposal.id} is pending. Approving publishes a command event — the agent never writes flags directly.</span>
        <button className="ok" onClick={approve}>Approve</button>
        <button className="danger" onClick={reject}>Reject</button>
      </div>}
      {msg && <p className="muted">{msg}</p>}
    </section>
  )
}

export default function App() {
  const [flags, setFlags] = useState([])
  const [configVersion, setConfigVersion] = useState(0)
  const [streamState, setStreamState] = useState('connecting')
  const [audit, setAudit] = useState([])
  const eventsRef = useRef(null)

  useEffect(() => {
    // Streaming-first: one SSE connection to the gateway (snapshot + deltas),
    // instead of polling a REST config endpoint.
    const es = new EventSource(`${GATEWAY}/stream/config`)
    eventsRef.current = es
    es.addEventListener('snapshot', e => {
      const snap = JSON.parse(e.data)
      setFlags(mergeSnapshot([], snap)); setConfigVersion(snap.configVersion); setStreamState(snap.stale ? 'stale (last-known-good)' : 'live')
    })
    es.addEventListener('flag-config', e => {
      const ev = JSON.parse(e.data)
      setFlags(prev => applyDelta(prev, ev)); setConfigVersion(ev.configVersion); setStreamState('live')
      fetchAudit().then(setAudit).catch(() => {})
    })
    es.onerror = () => setStreamState('disconnected — showing last-known-good')
    fetchAudit().then(setAudit).catch(() => {})
    return () => es.close()
  }, [])

  async function onRollout(key, pct) { try { await setRollout(key, pct) } catch (e) { alert(String(e.message || e)) } }
  async function onKill(key, currentlyEnabled) { try { await setKillSwitch(key, currentlyEnabled) } catch (e) { alert(String(e.message || e)) } }

  return (
    <main>
      <header className="topbar">
        <span className="icon big"><Icon d={ICONS.bolt} /></span>
        <div>
          <h1>Flag Platform</h1>
          <p className="muted">Distributed feature flags & release control · config version {configVersion} · stream: {streamState}</p>
        </div>
      </header>
      <section className="grid">
        {flags.map(f => <FlagCard key={f.key} flag={f} onRollout={onRollout} onKill={onKill} />)}
        {flags.length === 0 && <p className="muted">Waiting for the config stream from the gateway…</p>}
      </section>
      <RiskPanel flags={flags} />
      <section className="card wide">
        <header><span className="icon"><Icon d={ICONS.chart} /></span><h3>Audit stream</h3></header>
        <table>
          <thead><tr><th>Flag</th><th>Action</th><th>Actor</th><th>Version</th></tr></thead>
          <tbody>{[...audit].reverse().slice(0, 20).map(a => <tr key={a.id}><td>{a.flagKey}</td><td>{a.action}</td><td>{a.actor}</td><td>{a.version}</td></tr>)}</tbody>
        </table>
      </section>
    </main>
  )
}

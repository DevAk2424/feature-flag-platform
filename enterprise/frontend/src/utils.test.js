import { describe, it, expect } from 'vitest'
import { applyDelta, mergeSnapshot, rolloutLabel, riskTone, clampRollout } from './utils'

const flag = (key, pct, enabled = true) => ({ key, fallthroughPercentage: pct, enabled })

describe('streaming state helpers', () => {
  it('applies a delta by replacing the flag and keeping sort order', () => {
    const out = applyDelta([flag('a', 10), flag('b', 20)], { flagKey: 'b', flag: flag('b', 50) })
    expect(out.map(f => f.key)).toEqual(['a', 'b'])
    expect(out[1].fallthroughPercentage).toBe(50)
  })
  it('adds a new flag from a delta', () => {
    const out = applyDelta([flag('a', 10)], { flagKey: 'c', flag: flag('c', 5) })
    expect(out.map(f => f.key)).toEqual(['a', 'c'])
  })
  it('merges a snapshot wholesale', () => {
    const out = mergeSnapshot([flag('x', 1)], { flags: [flag('b', 2), flag('a', 3)] })
    expect(out.map(f => f.key)).toEqual(['a', 'b'])
  })
  it('labels kill-switched flags', () => {
    expect(rolloutLabel(flag('a', 80, false))).toBe('Kill switch ON')
    expect(rolloutLabel(flag('a', 80))).toBe('80% rollout')
  })
  it('maps risk actions to tones and clamps rollout', () => {
    expect(riskTone('ROLLBACK')).toBe('danger')
    expect(riskTone('HOLD')).toBe('warning')
    expect(clampRollout(140)).toBe(100)
    expect(clampRollout(-3)).toBe(0)
  })
})

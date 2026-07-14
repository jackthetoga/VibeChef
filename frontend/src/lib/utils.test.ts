import { describe, expect, it } from 'vitest'
import { formatDate, formatMinutes } from './utils'

describe('formatMinutes', () => {
  it('formats short and long durations', () => {
    expect(formatMinutes(35)).toBe('35 min')
    expect(formatMinutes(90)).toBe('1h 30m')
    expect(formatMinutes(120)).toBe('2h')
  })
})

describe('formatDate', () => {
  it('handles a missing expiry', () => {
    expect(formatDate()).toBe('No expiry')
  })

  it('keeps date-only expiries on the selected calendar day', () => {
    expect(formatDate('2026-07-13')).toBe('Jul 13')
  })
})

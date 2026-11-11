import { describe, expect, it } from 'vitest'
import { getLastMonthRange, toIsoDate } from './DateFilter'

describe('DateFilter helpers', () => {
  it('toIsoDate formats Date objects as YYYY-MM-DD with zero-padding', () => {
    const d = new Date(2026, 0, 5) // Jan 5, 2026
    expect(toIsoDate(d)).toBe('2026-01-05')
  })

  it('getLastMonthRange returns 1 month span ending today', () => {
    const range = getLastMonthRange()
    expect(range).toHaveProperty('from')
    expect(range).toHaveProperty('to')
    expect(range.from).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(range.to).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(new Date(range.from).getTime()).toBeLessThanOrEqual(new Date(range.to).getTime())
  })
})


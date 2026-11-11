import { describe, expect, it } from 'vitest'

import { buildLoginUrl, getSafeRedirectPath } from './redirectUtils'

describe('getSafeRedirectPath', () => {
  it('accepts safe internal paths including query and hash', () => {
    expect(getSafeRedirectPath('/leave-requests/137')).toBe('/leave-requests/137')
    expect(getSafeRedirectPath('/approvals?tab=early#top')).toBe('/approvals?tab=early#top')
  })

  it('rejects external URLs, protocol-relative URLs, login loops, and invalid inputs', () => {
    expect(getSafeRedirectPath('https://evil.example/steal')).toBe('')
    expect(getSafeRedirectPath('//evil.example/steal')).toBe('')
    expect(getSafeRedirectPath('/login')).toBe('')
    expect(getSafeRedirectPath('/login?next=/')).toBe('')
    expect(getSafeRedirectPath('')).toBe('')
    expect(getSafeRedirectPath(null)).toBe('')
  })
})

describe('buildLoginUrl', () => {
  it('returns plain /login for home path when not switching', () => {
    expect(buildLoginUrl({ pathname: '/', search: '', hash: '' })).toBe('/login')
  })

  it('preserves deep link path and search in next param', () => {
    expect(buildLoginUrl({ pathname: '/leave-requests/137', search: '', hash: '' })).toBe(
      '/login?next=%2Fleave-requests%2F137',
    )
  })

  it('includes switch=1 when switching accounts', () => {
    expect(
      buildLoginUrl(
        { pathname: '/admin/emails', search: '?status=FAILED', hash: '' },
        { switchAccount: true },
      ),
    ).toBe('/login?next=%2Fadmin%2Femails%3Fstatus%3DFAILED&switch=1')
    expect(buildLoginUrl('/', { switchAccount: true })).toBe('/login?switch=1')
  })
})

/**
 * Validate an internal post-login redirect target to prevent open redirects.
 * Returns empty string if the target is missing, external, or points to /login.
 */
export function getSafeRedirectPath(raw) {
  if (!raw || typeof raw !== 'string') return ''
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//') || trimmed.startsWith('/login')) {
    return ''
  }
  return trimmed
}

/**
 * Build the /login URL preserving the destination the user wanted to open.
 */
export function buildLoginUrl(location, { switchAccount = false } = {}) {
  const rawNext =
    typeof location === 'string'
      ? location
      : `${location?.pathname || ''}${location?.search || ''}${location?.hash || ''}`
  const safeNext = getSafeRedirectPath(rawNext)
  const params = new URLSearchParams()
  if (safeNext && safeNext !== '/') {
    params.set('next', safeNext)
  }
  if (switchAccount) {
    params.set('switch', '1')
  }
  const query = params.toString()
  return query ? `/login?${query}` : '/login'
}

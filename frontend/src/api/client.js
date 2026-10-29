import axios from 'axios'

import { createRefreshCoordinator } from './refreshCoordinator.js'

// The access token lives ONLY in this module variable — never in localStorage or
// sessionStorage (D-12 / "Security model"). A page script that manages to run
// (XSS) can read variables, but a token that is never persisted cannot be read
// back later from a disk-backed store, and a reload simply refreshes silently.
let accessToken = null

export function getAccessToken() {
  return accessToken
}

export function setAccessToken(token) {
  accessToken = token
}

export function clearAccessToken() {
  accessToken = null
}

// Clean up the token an older version of this app kept in localStorage.
try {
  window.localStorage?.removeItem('lms_token')
} catch {
  // storage may be unavailable (private mode); nothing to clean up then
}

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// A SameSite cookie is only sent back to the SAME SITE, so the app and the API
// must share a host in development: localhost and 127.0.0.1 are different sites.
if (import.meta.env.DEV && typeof window !== 'undefined') {
  try {
    const apiHost = new URL(API_BASE_URL).hostname
    if (window.location.hostname !== apiHost) {
      console.warn(
        `[lms] The app is running on ${window.location.hostname} but the API is on ` +
          `${apiHost}. Cookies will not work: open the app on the same host as the ` +
          'API (for example http://localhost:5173 with http://localhost:8000).',
      )
    }
  } catch {
    // an unparsable VITE_API_URL is reported by the first request instead
  }
}

const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
})

// --- session-ended notification -------------------------------------------

let sessionExpiredHandler = () => {}

export function setSessionExpiredHandler(handler) {
  sessionExpiredHandler = handler || (() => {})
}

function endSession() {
  clearAccessToken()
  sessionExpiredHandler()
}

// --- authentication calls -------------------------------------------------

const AUTH_CALLS = ['/auth/login', '/auth/refresh', '/auth/logout', '/auth/change-password']

function isAuthCall(url) {
  return AUTH_CALLS.some((path) => (url || '').startsWith(path))
}

async function doRefresh() {
  const { data } = await api.post('/auth/refresh')
  if (data?.access_token) setAccessToken(data.access_token)
  return data?.access_token ?? null
}

const coordinator = createRefreshCoordinator({ doRefresh })

// Startup refresh goes THROUGH the coordinator on purpose: React StrictMode runs
// effects twice in development, and the coordinator's single-flight guarantee
// turns those two mount effects into exactly one POST /auth/refresh.
export function restoreSession() {
  return coordinator.refresh()
}

// --- interceptors ---------------------------------------------------------

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const status = error.response?.status

    // Only an authenticated 401 is worth a silent refresh; login/refresh/logout
    // failures are real answers, and a request is retried at most once.
    if (
      status !== 401 ||
      !original ||
      original._lmsRetried ||
      isAuthCall(original.url)
    ) {
      return Promise.reject(error)
    }

    original._lmsRetried = true
    try {
      await coordinator.refresh()
    } catch (refreshError) {
      // No response at all = the network is down: the session is still valid.
      if (refreshError?.response) endSession()
      return Promise.reject(error)
    }
    return api(original)
  },
)

// --- helpers used by the pages -------------------------------------------

export function retryAfterSeconds(error) {
  const raw = error?.response?.headers?.['retry-after']
  const seconds = Number(raw)
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null
}

export function errorMessage(error, fallback = 'Something went wrong.') {
  if (error?.code === 'REFRESH_RACE') {
    return 'The session was refreshed by another tab. Please try again.'
  }

  const detail = error?.response?.data?.detail

  if (typeof detail === 'string') return detail

  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item
        const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null
        const message = item?.msg || 'Invalid value'
        return field ? `${field}: ${message}` : message
      })
      .join('; ')
  }

  if (error?.response?.status === 429) {
    return 'Too many attempts. Please wait a moment and try again.'
  }

  return fallback
}

export default api

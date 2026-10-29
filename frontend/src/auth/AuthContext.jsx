import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

import api, {
  clearAccessToken,
  restoreSession,
  setSessionExpiredHandler,
} from '../api/client'
import { startLiveStream, subscribeToChanges } from '../api/liveUpdates'

const AuthContext = createContext(null)

const CHANNEL_NAME = 'lms-auth'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sessionExpired, setSessionExpired] = useState(false)
  const channel = useRef(null)

  const endLocally = useCallback(() => {
    clearAccessToken()
    setUser(null)
  }, [])

  // The API layer tells us when a refresh proved the session is gone.
  useEffect(() => {
    setSessionExpiredHandler(() => {
      endLocally()
      setSessionExpired(true)
    })
    return () => setSessionExpiredHandler(null)
  }, [endLocally])

  // One tab logging out logs the others out too.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return undefined
    const bus = new BroadcastChannel(CHANNEL_NAME)
    channel.current = bus
    bus.onmessage = (event) => {
      if (event.data === 'logout') {
        endLocally()
      }
    }
    return () => {
      bus.close()
      channel.current = null
    }
  }, [endLocally])

  useEffect(() => {
    let cancelled = false
    const start = async () => {
      try {
        // Single-flight: StrictMode's double effect shares one refresh.
        await restoreSession()
        const { data } = await api.get('/auth/me')
        if (!cancelled) {
          setUser(data)
          setSessionExpired(false)
        }
      } catch {
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    start()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password) => {
    const body = new URLSearchParams({ username: email, password })
    const { data } = await api.post('/auth/login', body, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    // The login response carries the access token; the refresh token arrives as
    // an httpOnly cookie that JavaScript can never read.
    const { setAccessToken } = await import('../api/client.js')
    setAccessToken(data.access_token)
    const me = await api.get('/auth/me')
    setUser(me.data)
    setSessionExpired(false)
    return me.data
  }, [])

  // Live: any change made by ANY user, on ANY device, arrives over SSE and
  // makes the open screens refetch — no manual refresh (D-206).
  useEffect(() => {
    if (!user) return undefined
    return startLiveStream()
  }, [user])

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // logging out must never fail in the UI
    }
    endLocally()
    channel.current?.postMessage('logout')
  }, [endLocally])

  // Re-read the signed-in employee (for example after they changed their own
  // password, which clears the "must change" flag).
  const refreshUser = useCallback(async () => {
    try {
      const { data } = await api.get('/auth/me')
      setUser(data)
      return data
    } catch {
      return null
    }
  }, [])

  // While the flag is set, any successful write (the password change itself)
  // makes us re-read /auth/me, so the gate lifts at once instead of leaving the
  // person stuck on the screen (D-190).
  useEffect(() => {
    if (!user?.must_change_password) return undefined
    const unsubscribe = subscribeToChanges(refreshUser)
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe()
    }
  }, [user?.must_change_password, refreshUser])

  const logoutAll = useCallback(async () => {
    try {
      await api.post('/auth/logout-all')
    } catch {
      // ignore: the local cleanup below is what matters to this tab
    }
    endLocally()
    channel.current?.postMessage('logout')
  }, [endLocally])

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        sessionExpired,
        mustChangePassword: Boolean(user?.must_change_password),
        login,
        logout,
        logoutAll,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return context
}

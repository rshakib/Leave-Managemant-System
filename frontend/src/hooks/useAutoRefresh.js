import { useEffect, useRef } from 'react'

import { subscribeToChanges } from '../api/liveUpdates.js'

// Keeps the current view fresh without a manual refresh:
//
//  1. immediately after anything changes in this app (any successful write, or a
//     write in another tab) — via the live-updates signal;
//  2. when the tab becomes visible / regains focus (so coming back to a stale
//     screen pulls everything at once);
//  3. on a slow background poll, as a safety net for changes made elsewhere.
//
// Polling pauses while the tab is hidden, so an idle tab costs nothing.
export function useAutoRefresh(refresh, { intervalMs = 15000 } = {}) {
  const latest = useRef(refresh)

  useEffect(() => {
    latest.current = refresh
  })

  useEffect(() => {
    const run = () => {
      if (document.visibilityState === 'visible') latest.current?.()
    }

    const unsubscribe = subscribeToChanges(run)
    const timer = window.setInterval(run, intervalMs)

    const onActive = () => run()
    document.addEventListener('visibilitychange', onActive)
    window.addEventListener('focus', onActive)

    return () => {
      unsubscribe()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onActive)
      window.removeEventListener('focus', onActive)
    }
  }, [intervalMs])
}

import { useEffect, useRef } from 'react'

import { subscribeToChanges } from '../api/liveUpdates.js'

// Keeps the current view fresh without disruptive manual refreshes:
//
//  1. immediately when real data changes in the system (via SSE "/events" or
//     cross-tab BroadcastChannel);
//  2. when the user switches back to this tab (visibility / focus);
//  3. optionally on a slow background interval if intervalMs > 0 (disabled by
//     default so no blind repeating timer interrupts active user work).
export function useAutoRefresh(refresh, { intervalMs = 0 } = {}) {
  const latest = useRef(refresh)

  useEffect(() => {
    latest.current = refresh
  })

  useEffect(() => {
    const run = () => {
      if (document.visibilityState === 'visible') latest.current?.()
    }

    const unsubscribe = subscribeToChanges(run)
    const timer = intervalMs > 0 ? window.setInterval(run, intervalMs) : null

    const onActive = () => run()
    document.addEventListener('visibilitychange', onActive)
    window.addEventListener('focus', onActive)

    return () => {
      unsubscribe()
      if (timer) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onActive)
      window.removeEventListener('focus', onActive)
    }
  }, [intervalMs])
}

// Coordinates refresh-token rotation across every caller (and every tab).
//
// Built by a FACTORY with its dependencies injected (doRefresh / withLock /
// sleep) so it can be unit-tested without axios, React, a browser or a network.
//
// SINGLE-FLIGHT: while one refresh is running, every other caller awaits the
// very same promise instead of starting its own. When it settles — succeeded or
// failed — the shared slot is cleared so the next call starts fresh.

function defaultWithLock(name, fn) {
  if (typeof navigator !== 'undefined' && navigator.locks?.request) {
    // Web Locks: two TABS cannot refresh at the same moment either.
    return navigator.locks.request(name, fn)
  }
  return fn()
}

function isRaceError(error) {
  return (
    error?.code === 'REFRESH_RACE' ||
    error?.response?.data?.detail?.code === 'REFRESH_RACE'
  )
}

export function createRefreshCoordinator({
  doRefresh,
  withLock = defaultWithLock,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
}) {
  let inFlight = null

  async function runOnce() {
    try {
      return await doRefresh()
    } catch (error) {
      if (!isRaceError(error)) throw error
      // The other tab won this rotation: wait a moment, then try once more.
      await sleep(1000)
      return doRefresh()
    }
  }

  function refresh() {
    if (inFlight) return inFlight

    inFlight = (async () => {
      try {
        return await withLock('lms-refresh', runOnce)
      } finally {
        inFlight = null
      }
    })()

    return inFlight
  }

  return { refresh }
}

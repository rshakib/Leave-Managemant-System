// A tiny "something changed" signal shared by the whole app.
//
// - inside one tab: a window event, so every mounted view can re-fetch at once;
// - across tabs: a BroadcastChannel message, so a second tab stays in sync too.
//
// It carries no data on purpose: listeners simply re-run their own fetch, which
// keeps this trivially compatible with the existing REST API.

export const LIVE_EVENT = 'lms:data-changed'
const CHANNEL_NAME = 'lms-live'

let channel = null
if (typeof window !== 'undefined' && 'BroadcastChannel' in window) {
  channel = new BroadcastChannel(CHANNEL_NAME)
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
let stream = null

// One SSE connection per tab. The server sends only a version number, so every
// screen simply refreshes itself through the normal change signal.
export function startLiveStream() {
  if (typeof EventSource === 'undefined' || stream) return () => {}
  stream = new EventSource(`${API_BASE}/events`)
  stream.onmessage = () => notifyDataChanged()
  stream.onerror = () => {
    // EventSource reconnects on its own; nothing to do but let it.
  }
  return () => {
    stream?.close()
    stream = null
  }
}

export function notifyDataChanged() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(LIVE_EVENT))
  if (channel) channel.postMessage('changed')
}

export function subscribeToChanges(handler) {
  if (typeof window === 'undefined') return () => {}

  const relay = () => handler()

  window.addEventListener(LIVE_EVENT, relay)
  if (channel) channel.addEventListener('message', relay)

  return () => {
    window.removeEventListener(LIVE_EVENT, relay)
    if (channel) channel.removeEventListener('message', relay)
  }
}

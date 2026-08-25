/**
 * requestAnimationFrame backstop for frame-starved contexts.
 *
 * MapLibre's entire load pipeline is RAF-driven: the deferred style
 * `_load`, source-cache creation, tile scheduling, and every repaint are
 * queued with requestAnimationFrame. Chromium suspends RAF completely in
 * hidden / backgrounded tabs and in some headless-automation modes, so a
 * map opened there sits on a black canvas forever — `isStyleLoaded()`
 * stays false, `getStyle()` throws, no sourceCaches ever exist. Proven
 * 2026-07 on this exact app: swapping RAF for a timer let the same page
 * load fully in a backgrounded automation tab.
 *
 * The shim keeps the NATIVE rAF as the fast path and adds a timer
 * backstop per callback: whichever fires first wins and the loser is
 * cancelled. Foreground tabs behave natively (a visible frame beats the
 * timer essentially always); starved contexts degrade to timer-paced
 * frames (~10 fps, or browser-throttled slower when hidden) instead of
 * freezing. That makes every surface — analyst tab, background tab,
 * /geo-app/headless under any automation harness — load without
 * per-harness RAF hacks. Imported FIRST from main.jsx so it wraps RAF
 * before MapLibre (or anything else) captures a reference.
 */

const BACKSTOP_MS = 100

export function installRafBackstop() {
  if (typeof window === 'undefined') return
  if (window.__rafBackstopInstalled) return
  window.__rafBackstopInstalled = true

  const nativeRaf = window.requestAnimationFrame.bind(window)
  const nativeCancel = window.cancelAnimationFrame.bind(window)

  let nextHandle = 1
  const pending = new Map() // our handle -> { rafId, timerId }

  window.requestAnimationFrame = (callback) => {
    const handle = nextHandle++
    const fire = (timestamp) => {
      const entry = pending.get(handle)
      if (!entry) return // cancelled, or the other path already fired
      pending.delete(handle)
      nativeCancel(entry.rafId)
      clearTimeout(entry.timerId)
      callback(timestamp)
    }
    const rafId = nativeRaf(fire)
    const timerId = setTimeout(() => fire(performance.now()), BACKSTOP_MS)
    pending.set(handle, { rafId, timerId })
    return handle
  }

  window.cancelAnimationFrame = (handle) => {
    const entry = pending.get(handle)
    if (!entry) return
    pending.delete(handle)
    nativeCancel(entry.rafId)
    clearTimeout(entry.timerId)
  }
}

installRafBackstop()

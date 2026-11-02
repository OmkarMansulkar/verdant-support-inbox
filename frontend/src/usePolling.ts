import { useCallback, useEffect, useState } from 'react'

/**
 * Calls `load` now and then every `intervalMs` until the component unmounts.
 * The next call is scheduled only after the previous one finishes, so a slow
 * server (e.g. Render waking up) never gets overlapping requests. Polling is
 * skipped while the browser tab is hidden. `load` must be stable (useCallback).
 */
export function usePolling<T>(load: () => Promise<T>, intervalMs: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadCount, setReloadCount] = useState(0)

  useEffect(() => {
    let cancelled = false // set on unmount or reload: late results are ignored
    let timer: number | undefined

    async function tick() {
      if (!document.hidden) {
        try {
          const result = await load()
          if (!cancelled) {
            setData(result)
            setError(null)
          }
        } catch (e) {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e))
        }
      }
      if (!cancelled) timer = window.setTimeout(tick, intervalMs)
    }

    tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [load, intervalMs, reloadCount])

  const reload = useCallback(() => setReloadCount((n) => n + 1), [])
  return { data, error, reload }
}

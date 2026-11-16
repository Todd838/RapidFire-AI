import { useCallback, useEffect, useRef, useState } from 'react'

export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  enabled = true,
): { data: T | null; error: string | null; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  const hasDataRef = useRef(false)
  fetcherRef.current = fetcher

  const run = useCallback(() => {
    const ac = new AbortController()
    if (!hasDataRef.current) setLoading(true)

    void fetcherRef
      .current(ac.signal)
      .then((result) => {
        hasDataRef.current = true
        setData(result)
        setError(null)
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setError(e instanceof Error ? e.message : 'Request failed')
      })
      .finally(() => setLoading(false))

    return () => ac.abort()
  }, [])

  useEffect(() => {
    if (!enabled) return
    const cleanup = run()
    const timer = window.setInterval(run, intervalMs)
    return () => {
      window.clearInterval(timer)
      cleanup()
    }
  }, [run, intervalMs, enabled])

  return { data, error, loading, refresh: run }
}
import { useCallback, useEffect, useState } from 'react'

/** Minimal data-fetching hook: data, error, loading and a manual reload.
 *  Enough for a boilerplate; swap in TanStack Query when caching matters. */
export function useFetch<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    fetcher()
      .then((result) => !cancelled && (setData(result), setError(null)))
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(load, [load])

  return { data, error, loading, reload: load }
}

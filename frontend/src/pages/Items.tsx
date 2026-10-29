import { useState } from 'react'
import { api } from '@/api'
import { useFetch } from '@/hooks/useFetch'

export default function Items() {
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const { data, error, loading } = useFetch(() => api.items({ page, q: query || undefined }),
    [page, query])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Items</h1>
        <input
          value={query}
          onChange={(e) => {
            setPage(1)
            setQuery(e.target.value)
          }}
          placeholder="Search…"
          className="rounded-lg border border-base bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
        />
      </div>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-base text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Quantity</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-muted">Loading…</td></tr>
            )}
            {!loading && data?.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  Nothing here yet. Run <code>flask seed-demo</code>.
                </td>
              </tr>
            )}
            {data?.items.map((item) => (
              <tr key={item.id} className="border-b border-base last:border-0">
                <td className="px-4 py-3">{item.name}</td>
                <td className="px-4 py-3">{item.status}</td>
                <td className="px-4 py-3 text-right tabular-nums">{item.quantity}</td>
                <td className="px-4 py-3 text-muted">
                  {new Date(item.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted">
            Page {data.page} of {data.pages} · {data.total} items
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-lg border border-base px-3 py-1.5 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
              disabled={page >= data.pages}
              className="rounded-lg border border-base px-3 py-1.5 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

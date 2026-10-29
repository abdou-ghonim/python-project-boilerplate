import { api } from '@/api'
import { useFetch } from '@/hooks/useFetch'

export default function Dashboard() {
  const { data, error, loading } = useFetch(() => api.itemSummary())

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      {loading && <p className="text-sm text-muted">Loading…</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      {data && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Total items" value={data.total} />
          {Object.entries(data.by_status).map(([status, count]) => (
            <Stat key={status} label={status} value={count} />
          ))}
        </div>
      )}

      <p className="text-sm text-muted">
        This summary is served from <code>/api/items/summary</code> and cached in Redis
        for 60 seconds.
      </p>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

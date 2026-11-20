import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { analyticsFromCalls } from '../../lib/localPlatform'

const empty = { attempted: 0, connected: 0, completion_rate: 0 }

export function PerformancePage() {
  const { authReady } = useAuth()
  const { prefix } = useWorkspacePath()
  const local = useLocalPlatform()
  const [stats, setStats] = useState<{ attempted: number; connected: number; completion_rate: number } | null>(
    null,
  )

  useEffect(() => {
    if (!isApiEnabled()) {
      setStats(analyticsFromCalls(local.state.calls))
      return
    }
    if (!authReady) return
    if (!prefix) {
      setStats(empty)
      return
    }
    void apiFetch<{ attempted: number; connected: number; completion_rate: number }>(
      `${prefix}/analytics/overview`,
    )
      .then(setStats)
      .catch(() => setStats(empty))
  }, [prefix, authReady, local.state.calls])

  if (!stats) return <p className="text-sm text-karyuk-muted">Loading…</p>

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="text-2xl font-semibold">Performance</h1>
      {!isApiEnabled() && (
        <p className="mt-1 text-xs text-karyuk-muted">Computed from local conversation history.</p>
      )}
      <dl className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border bg-white p-4">
          <dt className="text-xs text-karyuk-muted">Attempted</dt>
          <dd className="text-2xl font-semibold">{stats.attempted}</dd>
        </div>
        <div className="rounded-2xl border bg-white p-4">
          <dt className="text-xs text-karyuk-muted">Connected</dt>
          <dd className="text-2xl font-semibold">{stats.connected}</dd>
        </div>
        <div className="rounded-2xl border bg-white p-4">
          <dt className="text-xs text-karyuk-muted">Completion rate</dt>
          <dd className="text-2xl font-semibold">{(stats.completion_rate * 100).toFixed(0)}%</dd>
        </div>
      </dl>
    </div>
  )
}
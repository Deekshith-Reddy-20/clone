import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { providerLabel } from '../../lib/providerLabel'

type CallRow = {
  id: string
  direction: string
  outcome: string
  duration_seconds: number
  cost_paise: number
  provider?: string | null
  disposition?: string | null
  is_test?: boolean
}

export function ConversationsPage() {
  const { prefix } = useWorkspacePath()
  const local = useLocalPlatform()
  const [calls, setCalls] = useState<CallRow[]>([])

  useEffect(() => {
    if (!isApiEnabled()) {
      setCalls(local.state.calls)
      return
    }
    if (!prefix) return
    void apiFetch<CallRow[]>(`${prefix}/calls`).then(setCalls)
  }, [prefix, local.state.calls])

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-2xl font-semibold text-karyuk-ink">Conversations</h1>
      {!isApiEnabled() && (
        <p className="mt-1 text-xs text-karyuk-muted">Local preview — includes demo + simulated calls.</p>
      )}
      <ul className="mt-6 space-y-2">
        {calls.map((c) => (
          <li key={c.id} className="flex items-center justify-between rounded-xl border bg-white px-4 py-3 text-sm">
            <span>
              {c.direction} · {c.outcome}
              {c.disposition ? ` · ${c.disposition}` : ''} · {c.duration_seconds}s
              {c.provider ? ` · ${providerLabel(c.provider)}` : ''}
              {c.is_test ? ' · TEST' : ''}
            </span>
            <Link to={`/app/conversations/${c.id}`} className="text-karyuk-green-dark">
              Details
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
import { useCallback, useEffect, useState } from 'react'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'

type BookingRequest = {
  id: string
  status: string
  caller_phone?: string | null
  details?: Record<string, unknown>
  note?: string | null
  notify_status?: string
  created_at?: string
}

export function BookingRequestsPage() {
  const { prefix } = useWorkspacePath()
  const [rows, setRows] = useState<BookingRequest[]>([])

  const load = useCallback(() => {
    if (!isApiEnabled() || !prefix) return
    void apiFetch<BookingRequest[]>(`${prefix}/booking-requests`).then(setRows)
  }, [prefix])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Booking requests</h1>
      <p className="text-sm text-karyuk-muted">
        Voice requests pending staff confirmation (no live PMS). Owner notify status is shown per request.
      </p>
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="rounded-xl border bg-white px-4 py-3 text-sm">
            <span className="font-medium">{r.status}</span> · {r.caller_phone ?? '—'}
            {r.notify_status ? (
              <span className="ml-2 text-xs text-karyuk-muted">notify: {r.notify_status}</span>
            ) : null}
            {r.note ? <p className="mt-1 text-xs text-karyuk-muted">{r.note}</p> : null}
            {r.details ? (
              <pre className="mt-1 overflow-auto text-[11px]">{JSON.stringify(r.details)}</pre>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}
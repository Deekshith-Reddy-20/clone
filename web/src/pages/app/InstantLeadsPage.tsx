import { useState } from 'react'
import { useWorkspaceCatalog } from '../../hooks/useWorkspaceCatalog'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { simulateOutboundCall } from '../../lib/localPlatform'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'

export function InstantLeadsPage() {
  const { prefix } = useWorkspacePath()
  const { employees, leads, loading } = useWorkspaceCatalog()
  const local = useLocalPlatform()
  const [leadId, setLeadId] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const placeCall = async () => {
    setError(null)
    setResult(null)
    if (!leadId || !employeeId) {
      setError('Select a lead and an employee.')
      return
    }
    try {
      if (!isApiEnabled()) {
        const lead = leads.find((l) => l.id === leadId)
        const res = simulateOutboundCall(local.workspaceId, {
          lead_id: leadId,
          employee_id: employeeId,
          phone: lead?.phone_e164,
          name: lead?.label.split(' · ')[0],
        })
        setResult(`Call placed (local): ${res.call_id}`)
        return
      }
      if (!prefix) {
        setError(apiBlockedMessage())
        return
      }
      const res = await apiFetch<{ call_id: string }>(`${prefix}/call-requests`, {
        method: 'POST',
        headers: { 'Idempotency-Key': `instant-${leadId}-${Date.now()}` },
        body: JSON.stringify({ lead_id: leadId, employee_id: employeeId }),
      })
      setResult(`Call placed: ${res.call_id}`)
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <h1 className="text-2xl font-semibold">Instant leads</h1>
      <p className="text-sm text-karyuk-muted">
        Dial a lead immediately with a published employee (M05).
      </p>
      <select
        className="w-full rounded border px-3 py-2 text-sm"
        value={leadId}
        onChange={(e) => setLeadId(e.target.value)}
        disabled={loading}
      >
        <option value="">{loading ? 'Loading leads…' : 'Select lead'}</option>
        {leads.map((l) => (
          <option key={l.id} value={l.id}>
            {l.label}
          </option>
        ))}
      </select>
      <select
        className="w-full rounded border px-3 py-2 text-sm"
        value={employeeId}
        onChange={(e) => setEmployeeId(e.target.value)}
        disabled={loading}
      >
        <option value="">{loading ? 'Loading employees…' : 'Select employee'}</option>
        {employees.map((e) => (
          <option key={e.id} value={e.id}>
            {e.label}
            {e.status ? ` (${e.status})` : ''}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={!leadId || !employeeId || loading}
        onClick={() => void placeCall()}
        className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white disabled:opacity-50"
      >
        Place instant call
      </button>
      {result && <p className="text-sm text-karyuk-green-dark">{result}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}
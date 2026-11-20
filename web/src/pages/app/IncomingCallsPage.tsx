import { useState } from 'react'
import { useWorkspaceCatalog } from '../../hooks/useWorkspaceCatalog'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { newId } from '../../lib/id'
import { patchPlatform } from '../../lib/localPlatform'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'

export function IncomingCallsPage() {
  const { prefix } = useWorkspacePath()
  const { employees, loading } = useWorkspaceCatalog()
  const local = useLocalPlatform()
  const [phone, setPhone] = useState('9876501234')
  const [employeeId, setEmployeeId] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const simulate = async () => {
    setError(null)
    setMsg(null)
    try {
      if (!isApiEnabled()) {
        const callId = newId()
        patchPlatform(local.workspaceId, (prev) => ({
          ...prev,
          calls: [
            {
              id: callId,
              direction: 'inbound',
              outcome: 'completed',
              duration_seconds: 55,
              cost_paise: 300,
              transcript: `Inbound from ${phone} answered by employee.`,
              summary: 'Local inbound simulation.',
              employee_id: employeeId || undefined,
            },
            ...prev.calls,
          ],
        }))
        local.refresh()
        setMsg(`Inbound call recorded (local): ${callId}`)
        return
      }
      if (!prefix) {
        setError(apiBlockedMessage())
        return
      }
      const caller =
        phone.trim().startsWith('+') ? phone.trim() : `+91${phone.replace(/\D/g, '')}`
      const res = await apiFetch<{ call_id: string }>(`${prefix}/incoming-calls/simulate`, {
        method: 'POST',
        body: JSON.stringify({ caller_phone: caller, employee_id: employeeId }),
      })
      setMsg(`Inbound call recorded: ${res.call_id}`)
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <h1 className="text-2xl font-semibold">Incoming calls</h1>
      <p className="text-sm text-karyuk-muted">Simulate provider inbound (staging).</p>
      <input
        className="w-full rounded border px-3 py-2 text-sm"
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        placeholder="Caller phone"
      />
      <select
        className="w-full rounded border px-3 py-2 text-sm"
        value={employeeId}
        onChange={(e) => setEmployeeId(e.target.value)}
        disabled={loading}
      >
        <option value="">{loading ? 'Loading employees…' : 'Select employee (optional)'}</option>
        {employees.map((e) => (
          <option key={e.id} value={e.id}>
            {e.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => void simulate()}
        className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white"
      >
        Simulate inbound call
      </button>
      {msg && <p className="text-sm text-karyuk-green-dark">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}
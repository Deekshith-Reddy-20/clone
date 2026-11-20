import { useCallback, useEffect, useState } from 'react'
import { useWorkspaceCatalog } from '../../hooks/useWorkspaceCatalog'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { newId } from '../../lib/id'
import { pushAudit } from '../../lib/localPlatform'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'

type Campaign = { id: string; name: string; status: string }

export function CampaignsPage() {
  const { prefix } = useWorkspacePath()
  const { employees, leads, loading: catalogLoading } = useWorkspaceCatalog()
  const local = useLocalPlatform()
  const [items, setItems] = useState<Campaign[]>([])
  const [name, setName] = useState('Follow-up batch')
  const [employeeId, setEmployeeId] = useState('')
  const [selectedLeadIds, setSelectedLeadIds] = useState<string[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!isApiEnabled()) {
      setItems(local.state.campaigns)
      return
    }
    if (!prefix) return
    void apiFetch<Campaign[]>(`${prefix}/campaigns`).then(setItems)
  }, [prefix, local.state.campaigns])

  useEffect(() => {
    load()
  }, [load])

  const create = async () => {
    setError(null)
    setMsg(null)
    try {
      if (!isApiEnabled()) {
        const id = newId()
        local.update((prev) => ({
          ...prev,
          campaigns: [{ id, name, status: 'draft' }, ...prev.campaigns],
        }))
        pushAudit(local.workspaceId, 'campaign.created', name)
        setMsg('Campaign created (local).')
        load()
        return
      }
      if (!prefix) {
        setError(apiBlockedMessage())
        return
      }
      if (!employeeId) {
        setError('Select an employee.')
        return
      }
      await apiFetch(`${prefix}/campaigns`, {
        method: 'POST',
        body: JSON.stringify({
          name,
          employee_id: employeeId,
          lead_ids: selectedLeadIds,
        }),
      })
      setMsg('Campaign created.')
      load()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const run = async (id: string) => {
    setError(null)
    try {
      if (!isApiEnabled()) {
        local.update((prev) => ({
          ...prev,
          campaigns: prev.campaigns.map((c) =>
            c.id === id ? { ...c, status: 'running' } : c,
          ),
        }))
        pushAudit(local.workspaceId, 'campaign.started', id.slice(0, 8))
        setMsg('Campaign started (local).')
        load()
        return
      }
      if (!prefix) {
        setError(apiBlockedMessage())
        return
      }
      await apiFetch(`${prefix}/campaigns/${id}/commands?command=start`, { method: 'POST' })
      setMsg('Campaign started.')
      load()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">Campaigns</h1>
      <p className="text-sm text-karyuk-muted">Batch outbound with employee + lead list (M06).</p>
      {msg && <p className="text-sm text-karyuk-green-dark">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="space-y-2 rounded-2xl border bg-white p-4">
        <input
          className="w-full rounded border px-2 py-1 text-sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name"
        />
        <select
          className="w-full rounded border px-2 py-1 text-sm"
          value={employeeId}
          onChange={(e) => setEmployeeId(e.target.value)}
          disabled={catalogLoading}
        >
          <option value="">Select employee</option>
          {employees.map((e) => (
            <option key={e.id} value={e.id}>
              {e.label}
            </option>
          ))}
        </select>
        <select
          multiple
          className="min-h-24 w-full rounded border px-2 py-1 text-sm"
          disabled={catalogLoading}
          onChange={(e) => {
            const opts = Array.from(e.target.selectedOptions).map((o) => o.value)
            setSelectedLeadIds(opts)
          }}
        >
          {leads.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-karyuk-muted">Shift+click to select multiple leads.</p>
        <button
          type="button"
          onClick={() => void create()}
          className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white"
        >
          Create campaign
        </button>
      </div>
      <ul className="space-y-2">
        {items.map((c) => (
          <li key={c.id} className="flex justify-between rounded-xl border bg-white px-4 py-3 text-sm">
            <span>
              {c.name} · {c.status}
            </span>
            <button type="button" onClick={() => void run(c.id)} className="text-karyuk-green-dark">
              Start
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
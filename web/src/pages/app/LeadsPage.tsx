import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { leadSourceLabel } from '../../lib/providerLabel'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { newId } from '../../lib/id'
import { pushAudit, type LocalLead } from '../../lib/localPlatform'

type Lead = {
  id: string
  name?: string
  phone_e164: string
  status: string
  lead_source?: string | null
  qualification?: string | null
  interest_level?: string | null
  follow_up_required?: boolean
  requirements?: string | null
  owner_notify_status?: string | null
  owner_notify_channel?: string | null
}

export function LeadsPage() {
  const { prefix } = useWorkspacePath()
  const local = useLocalPlatform()
  const [leads, setLeads] = useState<Lead[]>([])
  const [phone, setPhone] = useState('')
  const [name, setName] = useState('')
  const [csv, setCsv] = useState('name,phone\nTest User,9876543210')
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!isApiEnabled()) {
      setLeads(local.state.leads)
      return
    }
    if (!prefix) return
    void apiFetch<Lead[]>(`${prefix}/leads`).then(setLeads)
  }, [prefix, local.state.leads])

  useEffect(() => {
    load()
  }, [load])

  const addLead = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
  if (!isApiEnabled()) {
      const lead: LocalLead = {
        id: newId(),
        name: name || undefined,
        phone_e164: phone.startsWith('+') ? phone : `+91${phone.replace(/\D/g, '')}`,
        status: 'active',
      }
      local.update((prev) => ({
        ...prev,
        leads: [lead, ...prev.leads],
      }))
      pushAudit(local.workspaceId, 'lead.created', lead.phone_e164)
      setPhone('')
      setName('')
      setMsg('Lead added (saved locally).')
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    const normalized =
      phone.trim().startsWith('+') ? phone.trim() : `+91${phone.replace(/\D/g, '')}`
    await apiFetch(`${prefix}/leads`, {
      method: 'POST',
      body: JSON.stringify({ phone: normalized, name, consent_source: 'manual' }),
    })
    setPhone('')
    setMsg('Lead added.')
    load()
    } catch (err) {
      setError(formatActionError(err))
    }
  }

  const importCsv = async () => {
    setError(null)
    try {
    if (!isApiEnabled()) {
      const lines = csv.trim().split('\n').slice(1)
      let created = 0
      let invalid = 0
      const imported: LocalLead[] = []
      for (const line of lines) {
        const [n, p] = line.split(',').map((s) => s.trim())
        if (!p) {
          invalid++
          continue
        }
        imported.push({
          id: newId(),
          name: n || undefined,
          phone_e164: p.startsWith('+') ? p : `+91${p.replace(/\D/g, '')}`,
          status: 'active',
        })
        created++
      }
      local.update((prev) => ({ ...prev, leads: [...imported, ...prev.leads] }))
      pushAudit(local.workspaceId, 'lead.import', `${created} rows`)
      setMsg(`Imported ${created} rows (${invalid} invalid) — saved locally.`)
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    const res = await apiFetch<{ created: number; invalid_rows: number }>(`${prefix}/lead-imports`, {
      method: 'POST',
      body: JSON.stringify({ csv_text: csv }),
    })
    setMsg(`Imported ${res.created} rows (${res.invalid_rows} invalid).`)
    load()
    } catch (err) {
      setError(formatActionError(err))
    }
  }

  const content = (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-karyuk-ink">Leads</h1>
        <p className="mt-2 text-sm text-karyuk-muted">
          Manual entry, CSV import, suppression (M04).
          {!isApiEnabled() && (
            <span className="block mt-1 text-karyuk-green-dark">Local preview — data in browser storage.</span>
          )}
        </p>
      </div>
      {msg && <p className="text-sm text-karyuk-green-dark">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <form onSubmit={addLead} className="space-y-3 rounded-2xl border border-karyuk-border bg-white p-4">
        <input
          className="w-full rounded-xl border px-3 py-2 text-sm"
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="w-full rounded-xl border px-3 py-2 text-sm"
          placeholder="Phone"
          required
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <button type="submit" className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white">
          Add lead
        </button>
      </form>
      <div className="rounded-2xl border border-karyuk-border bg-white p-4">
        <textarea
          className="w-full rounded-xl border p-2 font-mono text-xs"
          rows={4}
          value={csv}
          onChange={(e) => setCsv(e.target.value)}
        />
        <button type="button" onClick={importCsv} className="mt-2 rounded-full border px-4 py-2 text-sm">
          Import CSV
        </button>
      </div>
      <ul className="space-y-2">
        {leads.map((l) => (
          <li key={l.id} className="rounded-xl border bg-white px-4 py-3 text-sm">
            <div>
              {l.name ?? '—'} · {l.phone_e164} ·{' '}
              <span className="text-karyuk-muted">{l.status}</span>
            </div>
            {(l.lead_source ||
              l.qualification ||
              l.interest_level ||
              l.follow_up_required ||
              l.owner_notify_status) && (
              <p className="mt-1 text-xs text-karyuk-muted">
                {l.lead_source ? `source: ${leadSourceLabel(l.lead_source)}` : null}
                {l.qualification ? ` · ${l.qualification}` : null}
                {l.interest_level ? ` · interest: ${l.interest_level}` : null}
                {l.follow_up_required ? ' · follow-up required' : null}
                {l.owner_notify_status ? ` · notify: ${l.owner_notify_status}` : null}
              </p>
            )}
            {l.requirements ? (
              <p className="mt-1 text-xs text-karyuk-ink">Question: {l.requirements}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )

  return content
}
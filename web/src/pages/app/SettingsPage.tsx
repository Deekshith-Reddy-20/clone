import { useEffect, useState } from 'react'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'
import { newId } from '../../lib/id'
import { pushAudit } from '../../lib/localPlatform'

export function SettingsPage() {
  const { prefix } = useWorkspacePath()
  const local = useLocalPlatform()
  const [timezone, setTimezone] = useState('Asia/Kolkata')
  const [retention, setRetention] = useState(90)
  const [audit, setAudit] = useState<{ action: string; summary: string }[]>([])
  const [knowledgeTitle, setKnowledgeTitle] = useState('FAQ')
  const [knowledgeBody, setKnowledgeBody] = useState('Check-in is at 2pm.')
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploadingPdf, setUploadingPdf] = useState(false)
  const [ownerEmail, setOwnerEmail] = useState('')
  const [ownerPhone, setOwnerPhone] = useState('')
  const [ownerWhatsapp, setOwnerWhatsapp] = useState('')
  const [notifyMeta, setNotifyMeta] = useState<Record<string, { verified?: boolean; last_test?: string }>>({})

  useEffect(() => {
    if (!isApiEnabled()) {
      setTimezone(local.state.timezone)
      setRetention(local.state.retention_days)
      setAudit(local.state.audit)
      return
    }
    if (!prefix) return
    void apiFetch<{
      timezone: string
      retention_days: number
      owner_notify?: {
        contacts: { email?: string; sms?: string; whatsapp?: string }
        channels?: Record<string, { verified?: boolean; last_test?: string }>
      }
    }>(`${prefix}/workspace-settings`).then((s) => {
      setTimezone(s.timezone)
      setRetention(s.retention_days)
      const c = s.owner_notify?.contacts
      if (c) {
        setOwnerEmail(c.email || '')
        setOwnerPhone(c.sms || '')
        setOwnerWhatsapp(c.whatsapp || '')
      }
      const ch = s.owner_notify?.channels || {}
      const meta: Record<string, { verified?: boolean; last_test?: string }> = {}
      for (const k of ['email', 'sms', 'whatsapp']) {
        meta[k] = { verified: ch[k]?.verified, last_test: ch[k]?.last_test }
      }
      setNotifyMeta(meta)
    })
    void apiFetch<{ action: string; summary: string }[]>(`${prefix}/audit-events`).then(setAudit)
  }, [prefix, local.state])

  const save = async () => {
    setError(null)
    setMsg(null)
    try {
    if (!isApiEnabled()) {
      local.update((prev) => ({ ...prev, timezone, retention_days: retention }))
      const next = pushAudit(local.workspaceId, 'settings.updated', timezone)
      setAudit(next.audit)
      setMsg('Settings saved (local).')
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    await apiFetch(`${prefix}/workspace-settings`, {
      method: 'PATCH',
      body: JSON.stringify({
        timezone,
        retention_days: retention,
        owner_notify: { email: ownerEmail, phone: ownerPhone, whatsapp: ownerWhatsapp },
      }),
    })
    setMsg('Settings saved.')
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const uploadKnowledgePdf = async (file: File) => {
    setError(null)
    setMsg(null)
    if (!isApiEnabled()) {
      setError('Connect the API to upload PDFs.')
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    setUploadingPdf(true)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await apiFetch<{ title: string; content_chars: number }>(
        `${prefix}/knowledge/sources/upload`,
        { method: 'POST', body },
      )
      setMsg(`PDF added: ${res.title} (${res.content_chars} chars). Republish employees to refresh calls.`)
    } catch (e) {
      setError(formatActionError(e))
    } finally {
      setUploadingPdf(false)
    }
  }

  const addKnowledge = async () => {
    setError(null)
    try {
    if (!isApiEnabled()) {
      local.update((prev) => ({
        ...prev,
        knowledge: [
          { id: newId(), title: knowledgeTitle, content: knowledgeBody },
          ...prev.knowledge,
        ],
      }))
      const next = pushAudit(local.workspaceId, 'knowledge.added', knowledgeTitle)
      setAudit(next.audit)
      setMsg('Knowledge added (local).')
      return
    }
    if (!prefix) {
      setError(apiBlockedMessage())
      return
    }
    await apiFetch(`${prefix}/knowledge/sources`, {
      method: 'POST',
      body: JSON.stringify({ title: knowledgeTitle, content: knowledgeBody }),
    })
    setMsg('Knowledge source added.')
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  useEffect(() => {
    if (!isApiEnabled()) setAudit(local.state.audit)
  }, [local.state.audit])

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <h1 className="text-2xl font-semibold">Settings</h1>
      {msg && <p className="text-sm text-karyuk-green-dark">{msg}</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      <section className="space-y-2 rounded-2xl border bg-white p-4">
        <label className="text-sm">Timezone</label>
        <input className="w-full rounded border px-2 py-1 text-sm" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
        <label className="text-sm">Retention (days)</label>
        <input type="number" className="w-full rounded border px-2 py-1 text-sm" value={retention} onChange={(e) => setRetention(Number(e.target.value))} />
        <button type="button" onClick={save} className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white">
          Save
        </button>
      </section>
      <section className="space-y-2 rounded-2xl border bg-white p-4">
        <h2 className="font-medium">Owner notifications</h2>
        <p className="text-xs text-karyuk-muted">
          Agent promises callback minutes only after a channel passes Send test notification (real send).
        </p>
        <input
          className="w-full rounded border px-2 py-1 text-sm"
          placeholder="Owner email"
          value={ownerEmail}
          onChange={(e) => setOwnerEmail(e.target.value)}
        />
        <input
          className="w-full rounded border px-2 py-1 text-sm"
          placeholder="Owner SMS phone (E.164)"
          value={ownerPhone}
          onChange={(e) => setOwnerPhone(e.target.value)}
        />
        <input
          className="w-full rounded border px-2 py-1 text-sm"
          placeholder="Owner WhatsApp (E.164)"
          value={ownerWhatsapp}
          onChange={(e) => setOwnerWhatsapp(e.target.value)}
        />
        {(['email', 'sms', 'whatsapp'] as const).map((ch) => (
          <div key={ch} className="flex flex-wrap items-center gap-2 text-xs">
            <span className="capitalize">{ch}</span>
            {notifyMeta[ch]?.verified ? (
              <span className="text-karyuk-green-dark">verified</span>
            ) : (
              <span className="text-karyuk-muted">unverified</span>
            )}
            {notifyMeta[ch]?.last_test ? (
              <span className="text-karyuk-muted">last: {notifyMeta[ch]?.last_test}</span>
            ) : null}
            <button
              type="button"
              className="rounded-full border px-3 py-1"
              disabled={!prefix}
              onClick={async () => {
                if (!prefix) return
                setError(null)
                try {
                  const r = await apiFetch<{ status: string; channel: string }>(
                    `${prefix}/workspace-settings/owner-notify/test`,
                    { method: 'POST', body: JSON.stringify({ channel: ch }) },
                  )
                  setMsg(`Test ${r.channel}: ${r.status}`)
                  setNotifyMeta((prev) => ({
                    ...prev,
                    [ch]: {
                      ...prev[ch],
                      last_test: r.status,
                      verified: r.status === 'sent' ? true : prev[ch]?.verified,
                    },
                  }))
                } catch (e) {
                  setError(formatActionError(e))
                }
              }}
            >
              Send test notification
            </button>
          </div>
        ))}
      </section>
      <section className="space-y-2 rounded-2xl border bg-white p-4">
        <h2 className="font-medium">Knowledge (M03)</h2>
        <p className="text-xs text-karyuk-muted">
          No website on the employee? Upload a PDF or add FAQ text — the voice agent answers only from
          here plus the employee brief after publish.
        </p>
        <label className="block text-xs font-medium text-karyuk-ink">
          Upload PDF (max 5 MB)
          <input
            type="file"
            accept="application/pdf,.pdf"
            className="mt-1 block w-full text-sm"
            disabled={uploadingPdf}
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void uploadKnowledgePdf(f)
              e.target.value = ''
            }}
          />
        </label>
        <input className="w-full rounded border px-2 py-1 text-sm" value={knowledgeTitle} onChange={(e) => setKnowledgeTitle(e.target.value)} />
        <textarea className="w-full rounded border p-2 text-sm" rows={3} value={knowledgeBody} onChange={(e) => setKnowledgeBody(e.target.value)} />
        <button type="button" onClick={addKnowledge} className="rounded-full border px-4 py-2 text-sm">
          Add knowledge source
        </button>
        {!isApiEnabled() && local.state.knowledge.length > 0 && (
          <ul className="text-xs text-karyuk-muted">
            {local.state.knowledge.map((k) => (
              <li key={k.id}>
                {k.title}: {k.content}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h2 className="font-medium">Audit trail</h2>
        <ul className="mt-2 space-y-1 text-sm text-karyuk-muted">
          {audit.map((a, i) => (
            <li key={i}>
              {a.action}: {a.summary}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
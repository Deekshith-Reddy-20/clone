import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { apiBlockedMessage, formatActionError } from '../../lib/actionFeedback'

type OutperoAgent = {
  id: string
  name: string
  slug: string
  status: string
  total_calls: number
  successful_calls: number
  failed_calls: number
  leads_generated: number
  last_activity_at?: string | null
  schema_cache?: Record<string, unknown>
  capabilities?: Record<string, boolean>
  webhook_signing_configured?: boolean
  action_secret_masked?: string | null
}

type OutperoCall = {
  id: string
  lead_id?: string | null
  outpero_agent_id?: string | null
  agent_name?: string | null
  lead_name?: string | null
  lead_phone?: string | null
  direction: string
  outcome: string
  disposition?: string | null
  duration_seconds: number
  transcript?: string | null
  summary?: string | null
  recording_url?: string | null
  captured_fields?: Record<string, unknown>
  is_test?: boolean
  created_at?: string
  realtime?: boolean
}

type OutperoLead = {
  id: string
  name?: string | null
  phone_e164: string
  status: string
  qualification?: string | null
  interest_level?: string | null
  follow_up_required?: boolean
  last_interaction_at?: string | null
  last_call?: {
    id: string
    created_at?: string
    disposition?: string | null
    outcome?: string | null
    outpero_agent_id?: string | null
  } | null
}

type OutperoStatus = {
  configured: boolean
  agent_count: number
  api_base_url: string
  webhook_url: string
  action_context_url: string
  supported_operations: string[]
  unsupported_operations: string[]
}

export function VoiceAgentsPage() {
  const { prefix } = useWorkspacePath()
  const base = prefix ? `${prefix}/outpero` : ''

  const [status, setStatus] = useState<OutperoStatus | null>(null)
  const [agents, setAgents] = useState<OutperoAgent[]>([])
  const [calls, setCalls] = useState<OutperoCall[]>([])
  const [leads, setLeads] = useState<OutperoLead[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [selectedCall, setSelectedCall] = useState<OutperoCall | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Register form
  const [regName, setRegName] = useState('')
  const [regSlug, setRegSlug] = useState('')
  const [regSecret, setRegSecret] = useState('')
  const [regWebhookSecret, setRegWebhookSecret] = useState('')

  // Test call form
  const [testPhone, setTestPhone] = useState('')
  const [testName, setTestName] = useState('')
  const [confirmCall, setConfirmCall] = useState(false)
  const [activeTestCallId, setActiveTestCallId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<OutperoCall | null>(null)

  // Lead filters
  const [leadQ, setLeadQ] = useState('')
  const [leadQualification, setLeadQualification] = useState('')
  const [callOutcomeFilter, setCallOutcomeFilter] = useState('')

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selectedAgentId) || null,
    [agents, selectedAgentId],
  )

  const loadAll = useCallback(async () => {
    if (!isApiEnabled()) {
      setError('API is not configured.')
      return
    }
    if (!base) {
      setError(apiBlockedMessage())
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [st, ag, cl, ld] = await Promise.all([
        apiFetch<OutperoStatus>(`${base}/status`),
        apiFetch<OutperoAgent[]>(`${base}/agents`),
        apiFetch<OutperoCall[]>(`${base}/calls?limit=50`),
        apiFetch<OutperoLead[]>(`${base}/leads`),
      ])
      setStatus(st)
      setAgents(ag)
      setCalls(cl)
      setLeads(ld)
      if (!selectedAgentId && ag.length > 0) {
        setSelectedAgentId(ag[0].id)
      }
    } catch (e) {
      setError(formatActionError(e))
    } finally {
      setLoading(false)
    }
  }, [base, selectedAgentId])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  // Poll active test call
  useEffect(() => {
    if (!activeTestCallId || !base) return
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const refreshed = await apiFetch<OutperoCall>(
            `${base}/calls/${activeTestCallId}/refresh`,
            { method: 'POST' },
          )
          setTestResult(refreshed)
          if (!refreshed.realtime) {
            setActiveTestCallId(null)
            void loadAll()
          }
        } catch {
          /* keep polling until terminal or manual refresh */
        }
      })()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [activeTestCallId, base, loadAll])

  const registerAgent = async () => {
    if (!base) return
    setError(null)
    setMsg(null)
    try {
      const created = await apiFetch<OutperoAgent>(`${base}/agents`, {
        method: 'POST',
        body: JSON.stringify({
          name: regName,
          slug: regSlug,
          lead_secret: regSecret,
          webhook_signing_secret: regWebhookSecret || null,
        }),
      })
      setMsg(`Registered agent ${created.name}`)
      setRegName('')
      setRegSlug('')
      setRegSecret('')
      setRegWebhookSecret('')
      setSelectedAgentId(created.id)
      await loadAll()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const refreshSchema = async () => {
    if (!base || !selectedAgentId) return
    setError(null)
    try {
      await apiFetch(`${base}/agents/${selectedAgentId}/refresh-schema`, { method: 'POST' })
      setMsg('Agent schema refreshed.')
      await loadAll()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const toggleAgentStatus = async () => {
    if (!base || !selectedAgent) return
    const next = selectedAgent.status === 'active' ? 'inactive' : 'active'
    setError(null)
    try {
      await apiFetch(`${base}/agents/${selectedAgent.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: next }),
      })
      setMsg(`Agent marked ${next}.`)
      await loadAll()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const startTestCall = async () => {
    if (!base || !selectedAgentId) return
    if (!confirmCall) {
      setError('Confirm that you want to place a real phone call.')
      return
    }
    setError(null)
    setMsg(null)
    setTestResult(null)
    try {
      const res = await apiFetch<{ call_id: string }>(
        `${base}/agents/${selectedAgentId}/test-calls`,
        {
          method: 'POST',
          body: JSON.stringify({
            phone: testPhone,
            name: testName || undefined,
            confirm: true,
            pre_call: { karyuk_test: true },
          }),
        },
      )
      setActiveTestCallId(res.call_id)
      setMsg(`Test call initiated: ${res.call_id}`)
      setConfirmCall(false)
      await loadAll()
    } catch (e) {
      setError(formatActionError(e))
    }
  }

  const filteredLeads = useMemo(() => {
    return leads.filter((l) => {
      if (leadQualification && l.qualification !== leadQualification) return false
      if (selectedAgentId) {
        const fromProfile = l.last_call?.outpero_agent_id === selectedAgentId
        // keep when no agent filter needed; when selected, prefer last_call match or show all agent leads from API
        if (l.last_call && l.last_call.outpero_agent_id && !fromProfile) {
          // still include if API already filtered; local filter is soft
        }
      }
      if (leadQ) {
        const q = leadQ.toLowerCase()
        const hay = `${l.name || ''} ${l.phone_e164} ${l.qualification || ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [leads, leadQualification, leadQ, selectedAgentId])

  const filteredCalls = useMemo(() => {
    return calls.filter((c) => {
      if (selectedAgentId && c.outpero_agent_id !== selectedAgentId) return false
      if (callOutcomeFilter && c.outcome !== callOutcomeFilter) return false
      return true
    })
  }, [calls, selectedAgentId, callOutcomeFilter])

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-karyuk-ink">Voice agents</h1>
        <p className="mt-1 text-sm text-karyuk-muted">
          Manage your AI callers, run test calls, and review leads synced into Karyuk automatically.
        </p>
        {status && (
          <p className="mt-2 text-xs text-karyuk-muted">
            Event webhook:{' '}
            <code className="rounded bg-karyuk-panel px-1.5 py-0.5">{status.webhook_url}</code>
          </p>
        )}
      </header>

      {error && <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {msg && <p className="rounded-xl border border-karyuk-border bg-karyuk-mint-soft px-3 py-2 text-sm text-karyuk-green-dark">{msg}</p>}
      {loading && <p className="text-sm text-karyuk-muted">Loading…</p>}

      {/* A. Agent overview */}
      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Agent overview</h2>
          <button
            type="button"
            onClick={() => void loadAll()}
            className="rounded-full border border-karyuk-border px-3 py-1.5 text-xs font-medium text-karyuk-muted hover:bg-white"
          >
            Refresh
          </button>
        </div>

        {agents.length === 0 ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950 space-y-2">
            <p className="font-medium">Voice agent not connected yet</p>
            <ol className="list-decimal pl-5 space-y-1 text-amber-900/90">
              <li>Open your voice-agent provider dashboard → Instant leads / Connect leads</li>
              <li>Copy the connection ID (slug) and API secret</li>
              <li>Paste them in the form below and click Save agent</li>
              <li>Then Instant leads / Team test calls will dial through this agent (no Exotel KYC)</li>
            </ol>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-karyuk-border bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-karyuk-border text-xs uppercase text-karyuk-muted">
                <tr>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">ID / Slug</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Calls</th>
                  <th className="px-3 py-2">OK / Fail</th>
                  <th className="px-3 py-2">Leads</th>
                  <th className="px-3 py-2">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => (
                  <tr
                    key={a.id}
                    className={`cursor-pointer border-b border-karyuk-border/70 hover:bg-karyuk-panel/60 ${
                      selectedAgentId === a.id ? 'bg-karyuk-mint-soft/40' : ''
                    }`}
                    onClick={() => setSelectedAgentId(a.id)}
                  >
                    <td className="px-3 py-2 font-medium">{a.name}</td>
                    <td className="px-3 py-2 text-xs text-karyuk-muted">
                      <div>{a.id.slice(0, 8)}…</div>
                      <div>{a.slug}</div>
                    </td>
                    <td className="px-3 py-2">{a.status}</td>
                    <td className="px-3 py-2">{a.total_calls}</td>
                    <td className="px-3 py-2">
                      {a.successful_calls} / {a.failed_calls}
                    </td>
                    <td className="px-3 py-2">{a.leads_generated}</td>
                    <td className="px-3 py-2 text-xs text-karyuk-muted">
                      {a.last_activity_at ? new Date(a.last_activity_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {selectedAgent && (
          <div className="rounded-2xl border border-karyuk-border bg-white p-4 text-sm space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-medium">{selectedAgent.name} configuration</p>
              <button
                type="button"
                onClick={() => void refreshSchema()}
                className="rounded-full border px-3 py-1 text-xs"
              >
                Refresh schema
              </button>
              <button
                type="button"
                onClick={() => void toggleAgentStatus()}
                className="rounded-full border px-3 py-1 text-xs"
              >
                Mark {selectedAgent.status === 'active' ? 'inactive' : 'active'}
              </button>
            </div>
            <p className="text-xs text-karyuk-muted">
              Webhook signing: {selectedAgent.webhook_signing_configured ? 'configured' : 'not set'} ·
              Action secret: {selectedAgent.action_secret_masked || '—'}
            </p>
            <pre className="max-h-48 overflow-auto rounded-xl bg-karyuk-panel p-3 text-xs">
              {JSON.stringify(selectedAgent.schema_cache || {}, null, 2)}
            </pre>
          </div>
        )}

        <div className="rounded-2xl border border-dashed border-karyuk-border bg-white p-4 space-y-3">
          <h3 className="text-sm font-semibold">Connect a voice agent</h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              className="rounded border px-3 py-2 text-sm"
              placeholder="Display name"
              value={regName}
              onChange={(e) => setRegName(e.target.value)}
            />
            <input
              className="rounded border px-3 py-2 text-sm"
              placeholder="Connection ID"
              value={regSlug}
              onChange={(e) => setRegSlug(e.target.value)}
            />
            <input
              className="rounded border px-3 py-2 text-sm"
              placeholder="API secret"
              value={regSecret}
              onChange={(e) => setRegSecret(e.target.value)}
              type="password"
            />
            <input
              className="rounded border px-3 py-2 text-sm"
              placeholder="Webhook signing secret (optional)"
              value={regWebhookSecret}
              onChange={(e) => setRegWebhookSecret(e.target.value)}
              type="password"
            />
          </div>
          <button
            type="button"
            disabled={!regName || !regSlug || !regSecret}
            onClick={() => void registerAgent()}
            className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            Save agent
          </button>
        </div>
      </section>

      {/* B. Test agent */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Test agent</h2>
        <p className="text-sm text-karyuk-muted">
          Places a real phone call to the number you enter. Confirmation is required — nothing dials
          when you open this page.
        </p>
        <div className="rounded-2xl border border-karyuk-border bg-white p-4 space-y-3">
          <select
            className="w-full rounded border px-3 py-2 text-sm"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
          >
            <option value="">Select agent</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.slug})
              </option>
            ))}
          </select>
          <input
            className="w-full rounded border px-3 py-2 text-sm"
            placeholder="Test phone (+91…)"
            value={testPhone}
            onChange={(e) => setTestPhone(e.target.value)}
          />
          <input
            className="w-full rounded border px-3 py-2 text-sm"
            placeholder="Name (optional pre-call variable)"
            value={testName}
            onChange={(e) => setTestName(e.target.value)}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={confirmCall}
              onChange={(e) => setConfirmCall(e.target.checked)}
            />
            I confirm this will dial the phone number above
          </label>
          <button
            type="button"
            disabled={!selectedAgentId || !testPhone || !confirmCall}
            onClick={() => void startTestCall()}
            className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            Start test call
          </button>
          {activeTestCallId && (
            <p className="text-xs text-karyuk-muted">
              Polling call status for {activeTestCallId}…
            </p>
          )}
          {testResult && (
            <div className="space-y-2 rounded-xl bg-karyuk-panel p-3 text-sm">
              <p>
                Status: <strong>{testResult.outcome}</strong>
                {testResult.disposition ? ` · ${testResult.disposition}` : ''} ·{' '}
                {testResult.duration_seconds}s
                {testResult.is_test ? ' · TEST' : ''}
              </p>
              {testResult.summary && <p className="text-karyuk-muted">{testResult.summary}</p>}
              {testResult.transcript && (
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-xs">
                  {testResult.transcript}
                </pre>
              )}
              {testResult.recording_url && (
                <a
                  className="text-karyuk-green-dark underline"
                  href={testResult.recording_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open recording
                </a>
              )}
              {testResult.captured_fields && (
                <pre className="max-h-32 overflow-auto text-xs">
                  {JSON.stringify(testResult.captured_fields, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Call activity */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-semibold">Call activity</h2>
          <select
            className="rounded border px-2 py-1.5 text-sm"
            value={callOutcomeFilter}
            onChange={(e) => setCallOutcomeFilter(e.target.value)}
          >
            <option value="">All outcomes</option>
            <option value="queued">queued</option>
            <option value="dialing">dialing</option>
            <option value="connected">connected</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
            <option value="no_answer">no_answer</option>
            <option value="busy">busy</option>
          </select>
        </div>
        {filteredCalls.length === 0 ? (
          <p className="text-sm text-karyuk-muted">No voice-agent calls yet.</p>
        ) : (
          <ul className="space-y-2">
            {filteredCalls.map((c) => (
              <li
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-white px-4 py-3 text-sm"
              >
                <div>
                  <p>
                    {c.direction} · {c.outcome}
                    {c.disposition ? ` · ${c.disposition}` : ''} · {c.duration_seconds}s
                    {c.is_test ? ' · TEST' : ''}
                  </p>
                  <p className="text-xs text-karyuk-muted">
                    {c.agent_name || 'Agent'} · {c.lead_name || c.lead_phone || '—'} ·{' '}
                    {c.created_at ? new Date(c.created_at).toLocaleString() : ''}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="text-karyuk-green-dark"
                    onClick={() => setSelectedCall(c)}
                  >
                    Details
                  </button>
                  <Link to={`/app/conversations/${c.id}`} className="text-karyuk-muted">
                    Full page
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
        {selectedCall && (
          <div className="rounded-2xl border border-karyuk-border bg-white p-4 text-sm space-y-2">
            <div className="flex justify-between">
              <p className="font-medium">Call {selectedCall.id}</p>
              <button type="button" className="text-xs text-karyuk-muted" onClick={() => setSelectedCall(null)}>
                Close
              </button>
            </div>
            <p>{selectedCall.summary || 'No summary yet.'}</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-xl bg-karyuk-panel p-3 text-xs">
              {selectedCall.transcript || 'No transcript yet.'}
            </pre>
            {selectedCall.recording_url && (
              <a className="text-karyuk-green-dark underline" href={selectedCall.recording_url} target="_blank" rel="noreferrer">
                Recording
              </a>
            )}
            {selectedCall.lead_id && (
              <Link className="block text-karyuk-green-dark" to="/app/leads">
                Open leads (lead {selectedCall.lead_id.slice(0, 8)}…)
              </Link>
            )}
          </div>
        )}
      </section>

      {/* C. Leads generated */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Leads generated by voice agents</h2>
        <div className="flex flex-wrap gap-2">
          <input
            className="rounded border px-3 py-2 text-sm"
            placeholder="Search name / phone"
            value={leadQ}
            onChange={(e) => setLeadQ(e.target.value)}
          />
          <select
            className="rounded border px-3 py-2 text-sm"
            value={leadQualification}
            onChange={(e) => setLeadQualification(e.target.value)}
          >
            <option value="">All qualifications</option>
            <option value="qualified">qualified</option>
            <option value="unqualified">unqualified</option>
            <option value="interested">interested</option>
            <option value="not_interested">not interested</option>
            <option value="follow_up_required">follow-up required</option>
          </select>
        </div>
        {filteredLeads.length === 0 ? (
          <p className="text-sm text-karyuk-muted">No leads from voice agents yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-karyuk-border bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-karyuk-border text-xs uppercase text-karyuk-muted">
                <tr>
                  <th className="px-3 py-2">Lead</th>
                  <th className="px-3 py-2">Phone</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Qualification</th>
                  <th className="px-3 py-2">Interest</th>
                  <th className="px-3 py-2">Last interaction</th>
                  <th className="px-3 py-2">Follow-up</th>
                </tr>
              </thead>
              <tbody>
                {filteredLeads.map((l) => (
                  <tr key={l.id} className="border-b border-karyuk-border/70">
                    <td className="px-3 py-2">
                      <Link className="text-karyuk-green-dark" to="/app/leads">
                        {l.name || 'Unnamed'}
                      </Link>
                    </td>
                    <td className="px-3 py-2">{l.phone_e164}</td>
                    <td className="px-3 py-2">{l.status}</td>
                    <td className="px-3 py-2">{l.qualification || '—'}</td>
                    <td className="px-3 py-2">{l.interest_level || '—'}</td>
                    <td className="px-3 py-2 text-xs">
                      {l.last_interaction_at
                        ? new Date(l.last_interaction_at).toLocaleString()
                        : '—'}
                    </td>
                    <td className="px-3 py-2">
                      {l.follow_up_required ? 'Required' : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {status && (
        <section className="rounded-2xl border border-karyuk-border bg-white p-4 text-xs text-karyuk-muted space-y-2">
          <p className="font-medium text-karyuk-ink">Connection details</p>
          <p>
            Mid-call context URL:{' '}
            <code className="rounded bg-karyuk-panel px-1">{status.action_context_url}</code>
          </p>
        </section>
      )}
    </div>
  )
}

import { Globe } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { LANGUAGES } from '../../data/employeeTemplates'
import { useWorkspace } from '../../context/WorkspaceContext'
import { useCallRealtime } from '../../hooks/useCallRealtime'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import type { CallMode } from '../../lib/workspace'
import { simulateOutboundCall } from '../../lib/localPlatform'
import { VoicePreviewPanel } from '../../components/VoicePreviewPanel'
import { BusinessProfileEditor } from '../../components/BusinessProfileEditor'

type ApiEmployee = {
  id: string
  status: string
  created_at: string
  draft: {
    revision: number
    brief: string
    language: string
    natural_spoken: boolean
    mode: string
    website_url?: string | null
    website_knowledge?: string | null
    operator_instructions?: string
    business_profile?: Record<string, unknown> | null
    profile_warnings?: string[]
    tts_speaker?: string
    updated_at: string
  } | null
  published_snapshot?: {
    version_number: number
    snapshot_revision: number
    brief: string
    language: string
    natural_spoken: boolean
    mode: string
    tts_speaker: string
    knowledge_chars: number
    brief_chars?: number
    website_knowledge_chars?: number
    workspace_knowledge_chars?: number
  } | null
  inbound_readiness?: {
    published: boolean
    assigned_numbers: string[]
    can_receive_inbound: boolean
  } | null
}

type TelephonyStatus = {
  mode: string
  exotel_configured: boolean
  livekit_configured: boolean
  public_api_base_url: string
  inbound_voice_mode?: string
}

const CALL_MODE_LABEL: Record<string, string> = {
  instant: 'Instant — outbound to new leads',
  bulk: 'Bulk — scheduled outbound campaigns',
  inbound: 'Inbound — answers when customers call your line',
}

const OUTCOME_LABEL: Record<string, string> = {
  queued: 'Queued',
  dialing: 'Dialing',
  ringing: 'Ringing',
  connected: 'On call',
  completed: 'Completed',
  failed: 'Failed',
  busy: 'Busy',
  no_answer: 'No answer',
  canceled: 'Canceled',
}

export function TeamPage() {
  const { employeeId } = useParams()
  const { prefix, workspaceId } = useWorkspacePath()
  const { state, publishEmployee, updateEmployeeDraft } = useWorkspace()
  const local = useLocalPlatform()
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [apiEmployees, setApiEmployees] = useState<ApiEmployee[]>([])
  const [loading, setLoading] = useState(isApiEnabled())
  const [telephony, setTelephony] = useState<TelephonyStatus | null>(null)
  const [editBrief, setEditBrief] = useState('')
  const [editLanguage, setEditLanguage] = useState<string>(LANGUAGES[0])
  const [editNatural, setEditNatural] = useState(true)
  const [editMode, setEditMode] = useState<CallMode>('instant')
  const [editSpeaker, setEditSpeaker] = useState('shubh')
  const [savingDraft, setSavingDraft] = useState(false)
  const [editWebsiteUrl, setEditWebsiteUrl] = useState('')
  const [websiteKnowledge, setWebsiteKnowledge] = useState('')
  const [editProfile, setEditProfile] = useState<Record<string, unknown>>({})
  const [profileWarnings, setProfileWarnings] = useState<string[]>([])
  const [analyzingWebsite, setAnalyzingWebsite] = useState(false)
  const [testPhone, setTestPhone] = useState('')
  const [testName, setTestName] = useState('Test lead')
  const [goLive, setGoLive] = useState<{
    ready: boolean
    vad_engine?: string
    voice_barge_in?: string
    last_e2e_p50_ms?: number | null
    items: { ok: boolean; label: string; detail?: string }[]
  } | null>(null)
  const [activeCallId, setActiveCallId] = useState<string | null>(null)
  const { call: liveCall } = useCallRealtime(activeCallId, local.workspaceId, prefix)

  const reloadEmployees = useCallback(() => {
    if (!isApiEnabled() || !prefix) return
    return apiFetch<ApiEmployee[]>(`${prefix}/employees`).then(setApiEmployees)
  }, [prefix])

  useEffect(() => {
    if (!isApiEnabled() || !prefix) {
      setLoading(false)
      return
    }
    setLoading(true)
    void reloadEmployees()?.finally(() => setLoading(false))
    void apiFetch<TelephonyStatus>(`${prefix}/telephony/status`).then(setTelephony)
  }, [prefix, reloadEmployees])

  const apiSelected = employeeId ? apiEmployees.find((e) => e.id === employeeId) : null
  const localSelected = employeeId ? state.employees.find((e) => e.id === employeeId) : null

  useEffect(() => {
    if (apiSelected?.draft) {
      setEditBrief(apiSelected.draft.brief)
      setEditLanguage(apiSelected.draft.language)
      setEditNatural(apiSelected.draft.natural_spoken)
      setEditMode(apiSelected.draft.mode as CallMode)
      setEditWebsiteUrl(apiSelected.draft.website_url ?? '')
      setWebsiteKnowledge(apiSelected.draft.website_knowledge ?? '')
      setEditProfile((apiSelected.draft.business_profile as Record<string, unknown>) ?? {})
      setProfileWarnings(apiSelected.draft.profile_warnings ?? [])
      setEditSpeaker(apiSelected.draft.tts_speaker ?? 'shubh')
    } else if (localSelected) {
      setEditBrief(localSelected.brief)
      setEditLanguage(localSelected.language)
      setEditNatural(localSelected.naturalSpoken)
      setEditMode(localSelected.mode)
    }
  }, [apiSelected, localSelected])

  useEffect(() => {
    if (!isApiEnabled() || !prefix || !employeeId) {
      setGoLive(null)
      return
    }
    void apiFetch<NonNullable<typeof goLive>>(`${prefix}/employees/${employeeId}/readiness`).then(
      setGoLive,
    )
  }, [prefix, employeeId, apiSelected?.status])

  const useApiList = isApiEnabled() && apiEmployees.length > 0
  const hasLocal = state.employees.length > 0
  const hasApi = apiEmployees.length > 0

  const saveDraft = async () => {
    if (editBrief.trim().length < 12) {
      setActionMsg('Brief must be at least 12 characters.')
      return
    }
    setSavingDraft(true)
    try {
      if (isApiEnabled() && prefix && employeeId && (apiSelected?.draft || apiSelected)) {
        await apiFetch(`${prefix}/employees/${employeeId}/draft`, {
          method: 'PATCH',
          body: JSON.stringify({
            brief: editBrief,
            language: editLanguage,
            natural_spoken: editNatural,
            mode: editMode,
            revision: apiSelected.draft?.revision ?? 1,
            website_url: editWebsiteUrl.trim() || null,
            website_knowledge: websiteKnowledge.trim() || null,
            business_profile: editProfile,
            tts_speaker: editSpeaker,
          }),
        })
        await reloadEmployees()
        setActionMsg('Draft saved.')
      } else if (employeeId) {
        updateEmployeeDraft(employeeId, {
          brief: editBrief,
          language: editLanguage,
          naturalSpoken: editNatural,
          mode: editMode,
        })
        setActionMsg('Draft saved locally.')
      }
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : 'Could not save draft')
    } finally {
      setSavingDraft(false)
    }
  }

  const analyzeWebsite = async () => {
    if (!editWebsiteUrl.trim()) {
      setActionMsg('Enter a website URL first (e.g. https://yourhotel.com).')
      return
    }
    if (!isApiEnabled() || !prefix || !employeeId) {
      setActionMsg('Connect the API to analyze websites.')
      return
    }
    setAnalyzingWebsite(true)
    setActionMsg(null)
    try {
      const res = await apiFetch<{
        website_url: string
        website_knowledge: string
        revision: number
      }>(`${prefix}/employees/${employeeId}/website/analyze`, {
        method: 'POST',
        body: JSON.stringify({ url: editWebsiteUrl.trim() }),
      })
      setEditWebsiteUrl(res.website_url)
      setWebsiteKnowledge(res.website_knowledge)
      await reloadEmployees()
      setActionMsg('Website analyzed — republish to use on live calls.')
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : 'Website analysis failed')
    } finally {
      setAnalyzingWebsite(false)
    }
  }

  const publish = async () => {
    if (!employeeId) return
  try {
    if (isApiEnabled() && prefix) {
      const version = await apiFetch<{ version_number: number }>(
        `${prefix}/employees/${employeeId}/publish`,
        { method: 'POST' },
      )
      setActionMsg(`Published v${version.version_number}.`)
      await reloadEmployees()
      return
    }
    publishEmployee(employeeId)
    setActionMsg('Published (local preview).')
  } catch (e) {
    setActionMsg(e instanceof Error ? e.message : 'Publish failed')
  }
  }

  const testCall = async () => {
    if (!employeeId || !testPhone.trim()) {
      setActionMsg('Enter a phone number for the test call.')
      return
    }
    try {
    if (isApiEnabled() && prefix) {
      const res = await apiFetch<{
        call_id: string
        outcome: string
        provider?: string
        realtime?: boolean
      }>(`${prefix}/employees/${employeeId}/test-calls`, {
        method: 'POST',
        body: JSON.stringify({
          phone: testPhone.trim().startsWith('+')
            ? testPhone.trim()
            : `+91${testPhone.replace(/\D/g, '')}`,
          name: testName,
        }),
      })
      setActiveCallId(res.call_id)
      setActionMsg(
        res.provider === 'exotel'
          ? `Live call started (${res.outcome}).`
          : `Test call started (${res.outcome}).`,
      )
      return
    }
    const res = simulateOutboundCall(local.workspaceId, {
      employee_id: employeeId,
      phone: testPhone,
      name: testName,
    })
    setActiveCallId(res.call_id)
    setActionMsg('Test call started (local simulation).')
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : 'Test call failed')
    }
  }

  if (loading) return <p className="text-sm text-karyuk-muted">Loading team…</p>

  if (!hasLocal && !hasApi && !employeeId) {
    return (
      <div className="mx-auto max-w-lg text-center">
        <h1 className="text-2xl font-semibold text-karyuk-ink">Your team</h1>
        <p className="mt-2 text-karyuk-muted">No employees yet.</p>
        <Link
          to="/app"
          className="mt-6 inline-flex rounded-full bg-karyuk-green-dark px-5 py-2.5 text-sm font-medium text-white"
        >
          Hire your first employee
        </Link>
      </div>
    )
  }

  if (employeeId && !localSelected && !apiSelected) {
    if (loading && isApiEnabled()) {
      return <p className="text-sm text-karyuk-muted">Loading employee…</p>
    }
    return (
      <div className="mx-auto max-w-lg">
        <p className="text-karyuk-muted">Employee not found.</p>
        <Link to="/app/team" className="mt-4 text-sm font-medium text-karyuk-green-dark">
          Back to team
        </Link>
      </div>
    )
  }

  const published =
    localSelected?.status === 'published' || apiSelected?.status === 'published'

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/app/team" className="text-sm text-karyuk-muted hover:text-karyuk-ink">
            ← Your team
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-karyuk-ink">Employee</h1>
        </div>
        {telephony && (
          <div className="rounded-xl border border-karyuk-border bg-karyuk-panel/60 px-3 py-2 text-xs text-karyuk-muted">
            Inbound calls:{' '}
            <span className="font-medium text-karyuk-ink">
              {telephony.exotel_configured ? 'Exotel PSTN' : 'Exotel not configured'}
            </span>
            {telephony.inbound_voice_mode === 'sarvam' ? ' · Sarvam STT/TTS' : ''}
            {telephony.inbound_voice_mode === 'livekit' && telephony.livekit_configured
              ? ' · LiveKit media'
              : ''}
            {telephony.inbound_voice_mode === 'livekit' && !telephony.livekit_configured
              ? ' · LiveKit configured in env but not active'
              : ''}
          </div>
        )}
        {!isApiEnabled() && (
          <div className="rounded-xl border border-karyuk-border bg-karyuk-mint-soft px-3 py-2 text-xs text-karyuk-green-dark">
            Local preview — add Exotel / LiveKit in API `.env` for live calls
          </div>
        )}
      </div>

      {!employeeId && (
        <ul className="space-y-3">
          {(useApiList ? apiEmployees : state.employees).map((e) => {
            const id = 'id' in e ? e.id : (e as { id: string }).id
            const brief =
              'brief' in e
                ? (e as { brief: string }).brief
                : (e as ApiEmployee).draft?.brief ?? ''
            const status =
              'status' in e && typeof (e as ApiEmployee).status === 'string'
                ? (e as ApiEmployee).status
                : (e as { status?: string }).status ?? 'draft'
            const meta =
              'language' in e
                ? `${(e as { language: string }).language} · ${(e as { mode: string }).mode}`
                : `${(e as ApiEmployee).draft?.language} · ${(e as ApiEmployee).draft?.mode}`
            return (
              <li key={id}>
                <Link
                  to={`/app/team/${id}`}
                  className="block rounded-2xl border border-karyuk-border bg-white p-4 hover:border-karyuk-mint/40"
                >
                  <div className="flex justify-between gap-2">
                    <p className="line-clamp-2 font-medium text-karyuk-ink">{brief}</p>
                    <span className="shrink-0 text-[10px] uppercase tracking-wide text-karyuk-muted">
                      {status}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-karyuk-muted">{meta}</p>
                </Link>
              </li>
            )
          })}
        </ul>
      )}

      {employeeId && (localSelected || apiSelected) && (
        <article className="space-y-6 rounded-2xl border border-karyuk-border bg-white p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wide text-karyuk-muted">
            {published ? 'Published · live callers use the snapshot below' : 'Draft · publish to pin live calls'}
          </p>

          {goLive && (
            <div
              className={`rounded-xl border p-3 text-xs ${
                goLive.ready ? 'border-green-600/40 bg-green-50' : 'border-red-400/40 bg-red-50'
              }`}
            >
              <p className="font-semibold text-karyuk-ink">
                Go-live readiness: {goLive.ready ? 'GREEN' : 'RED'}
              </p>
              <p className="mt-1 text-karyuk-muted">
                vad={goLive.vad_engine} · barge-in={goLive.voice_barge_in}
                {goLive.last_e2e_p50_ms != null ? ` · last e2e p50 ${goLive.last_e2e_p50_ms}ms` : ''}
              </p>
              <ul className="mt-2 space-y-1">
                {goLive.items.map((it) => (
                  <li key={it.label} className={it.ok ? 'text-green-900' : 'text-red-800'}>
                    {it.ok ? '✓' : '✗'} {it.label}
                    {it.detail ? ` — ${it.detail}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {apiSelected?.inbound_readiness && (
            <div className="rounded-xl border border-karyuk-border bg-karyuk-panel/50 p-3 text-xs text-karyuk-muted">
              <p className="font-medium text-karyuk-ink">Inbound line readiness</p>
              <ul className="mt-2 list-inside list-disc space-y-1">
                <li>
                  Published: {apiSelected.inbound_readiness.published ? 'yes' : 'no — publish first'}
                </li>
                <li>
                  Number assigned:{' '}
                  {apiSelected.inbound_readiness.assigned_numbers.length
                    ? apiSelected.inbound_readiness.assigned_numbers.join(', ')
                    : 'none — set in Numbers & channels'}
                </li>
                <li>
                  Can receive calls:{' '}
                  {apiSelected.inbound_readiness.can_receive_inbound ? 'yes' : 'not yet'}
                </li>
              </ul>
            </div>
          )}

          {apiSelected?.published_snapshot && (
            <section className="space-y-2 rounded-xl border border-karyuk-green-dark/30 bg-karyuk-mint-soft/20 p-4">
              <h2 className="text-sm font-semibold text-karyuk-ink">Published on live calls</h2>
              <p className="text-[11px] text-karyuk-muted">
                Draft edits below do not change inbound until you publish again. Voice preview can try
                another Sarvam voice without affecting the line.
              </p>
              <dl className="grid gap-1 text-xs text-karyuk-muted sm:grid-cols-2">
                <span>
                  Version {apiSelected.published_snapshot.version_number} · snapshot rev{' '}
                  {apiSelected.published_snapshot.snapshot_revision}
                </span>
                <span>
                  Mode: {CALL_MODE_LABEL[apiSelected.published_snapshot.mode] ?? apiSelected.published_snapshot.mode}
                </span>
                <span>Language: {apiSelected.published_snapshot.language}</span>
                <span>
                  Voice on live calls: {apiSelected.published_snapshot.tts_speaker} (draft picker
                  below — publish after changing)
                </span>
                <span className="sm:col-span-2">
                  Grounding on live calls:{' '}
                  {apiSelected.published_snapshot.knowledge_chars > 0
                    ? `${apiSelected.published_snapshot.knowledge_chars} chars (brief ${
                        apiSelected.published_snapshot.brief_chars ?? 0
                      } · site ${apiSelected.published_snapshot.website_knowledge_chars ?? 0} · workspace ${
                        apiSelected.published_snapshot.workspace_knowledge_chars ?? 0
                      })`
                    : 'brief empty — add brief or knowledge and republish'}
                </span>
              </dl>
            </section>
          )}

          <section className="space-y-3">
            <label className="text-sm font-medium text-karyuk-ink">Brief</label>
            <textarea
              className="min-h-28 w-full rounded-xl border border-karyuk-border px-3 py-2 text-sm"
              value={editBrief}
              onChange={(e) => setEditBrief(e.target.value)}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="text-xs text-karyuk-muted">Language</label>
                <select
                  className="mt-1 w-full rounded-lg border px-2 py-2 text-sm"
                  value={editLanguage}
                  onChange={(e) => setEditLanguage(e.target.value)}
                >
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-karyuk-muted">Call mode (draft)</label>
                <select
                  className="mt-1 w-full rounded-lg border px-2 py-2 text-sm"
                  value={editMode}
                  onChange={(e) => setEditMode(e.target.value as CallMode)}
                >
                  <option value="instant">{CALL_MODE_LABEL.instant}</option>
                  <option value="bulk">{CALL_MODE_LABEL.bulk}</option>
                  <option value="inbound">{CALL_MODE_LABEL.inbound}</option>
                </select>
                {apiSelected?.published_snapshot &&
                  apiSelected.published_snapshot.mode !== editMode && (
                    <p className="mt-1 text-[11px] text-amber-800">
                      Live calls still use published mode:{' '}
                      {CALL_MODE_LABEL[apiSelected.published_snapshot.mode] ??
                        apiSelected.published_snapshot.mode}
                    </p>
                  )}
              </div>
            </div>
            <StaticVoiceRow speaker={editSpeaker} onChange={setEditSpeaker} />
            <label className="flex items-center gap-2 text-sm text-karyuk-muted">
              <input
                type="checkbox"
                checked={editNatural}
                onChange={(e) => setEditNatural(e.target.checked)}
              />
              Natural spoken delivery
            </label>
            <button
              type="button"
              disabled={savingDraft}
              onClick={() => void saveDraft()}
              className="rounded-full border border-karyuk-border px-4 py-2 text-sm font-medium hover:bg-karyuk-panel"
            >
              {savingDraft ? 'Saving…' : 'Save draft'}
            </button>
          </section>

          <section className="space-y-3 rounded-xl border border-karyuk-border bg-karyuk-mint-soft/30 p-4">
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-karyuk-green-dark" aria-hidden />
              <h2 className="text-sm font-semibold text-karyuk-ink">Website</h2>
            </div>
            <p className="text-xs text-karyuk-muted">
              AI reads the site and answers from it — availability, booking steps, hotel or business
              details, and confirmation wording. No website? Upload a PDF under Settings → Knowledge,
              or paste facts below; calls use only that published material.
            </p>
            <input
              type="url"
              className="w-full rounded-xl border border-karyuk-border bg-white px-3 py-2 text-sm"
              placeholder="https://your-hotel-or-business.com"
              value={editWebsiteUrl}
              onChange={(e) => setEditWebsiteUrl(e.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={analyzingWebsite || !editWebsiteUrl.trim()}
                onClick={() => void analyzeWebsite()}
                className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
              >
                {analyzingWebsite ? 'Analyzing…' : 'Analyze website'}
              </button>
            </div>
            <div>
              <label className="text-xs font-medium text-karyuk-ink">
                Knowledge base (draft — saved with Save draft; workspace FAQs pinned on publish)
              </label>
              <textarea
                className="mt-1 min-h-28 w-full rounded-xl border border-karyuk-border bg-white px-3 py-2 text-[11px] leading-relaxed"
                placeholder="Facts from website analyze, or paste hours, departments, policies…"
                value={websiteKnowledge}
                onChange={(e) => setWebsiteKnowledge(e.target.value)}
              />
            </div>
          </section>

          <BusinessProfileEditor
            value={editProfile}
            warnings={profileWarnings}
            onChange={(p) => setEditProfile(p as Record<string, unknown>)}
          />

          {workspaceId && employeeId && (apiSelected || localSelected) ? (
            <VoicePreviewPanel
              workspaceId={workspaceId}
              employeeId={employeeId}
              disabled={!editBrief.trim()}
            />
          ) : null}

          <section className="rounded-xl border border-dashed border-karyuk-border bg-karyuk-panel/40 p-4">
            <h2 className="text-sm font-semibold text-karyuk-ink">Test call</h2>
            <p className="mt-1 text-xs text-karyuk-muted">
              Publish first. With Exotel keys, this places a real outbound call.
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <input
                className="rounded-lg border px-3 py-2 text-sm"
                placeholder="Phone (e.g. 9876543210)"
                value={testPhone}
                onChange={(e) => setTestPhone(e.target.value)}
              />
              <input
                className="rounded-lg border px-3 py-2 text-sm"
                placeholder="Lead name"
                value={testName}
                onChange={(e) => setTestName(e.target.value)}
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={published}
                onClick={() => void publish()}
                className="rounded-full bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
              >
                {published ? 'Published' : 'Publish'}
              </button>
              <button
                type="button"
                disabled={!published}
                onClick={() => void testCall()}
                className="rounded-full border px-4 py-2 text-sm font-medium disabled:opacity-40"
              >
                Place test call
              </button>
              <Link
                to="/app/numbers"
                className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm font-medium text-white"
              >
                Connect number
              </Link>
            </div>

            {liveCall && (
              <div className="mt-4 rounded-lg bg-white p-3 text-sm">
                <p className="font-medium text-karyuk-ink">
                  {OUTCOME_LABEL[liveCall.outcome] ?? liveCall.outcome}
                  {liveCall.realtime && (
                    <span className="ml-2 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
                  )}
                </p>
                {liveCall.provider && (
                  <p className="text-xs text-karyuk-muted">Provider: {liveCall.provider}</p>
                )}
                {liveCall.livekit_room && (
                  <p className="text-xs text-karyuk-muted">LiveKit room: {liveCall.livekit_room}</p>
                )}
                {liveCall.transcript && liveCall.outcome === 'completed' && (
                  <p className="mt-2 whitespace-pre-wrap text-xs text-karyuk-muted">{liveCall.transcript}</p>
                )}
                <Link
                  to={`/app/conversations/${liveCall.id}`}
                  className="mt-2 inline-block text-xs text-karyuk-green-dark"
                >
                  Open conversation
                </Link>
              </div>
            )}
          </section>

          {actionMsg && <p className="text-sm text-karyuk-green-dark">{actionMsg}</p>}
        </article>
      )}
    </div>
  )
}

const HIRE_VOICES = [
  { id: 'priya', label: 'Priya (female)' },
  { id: 'neha', label: 'Neha (female)' },
  { id: 'shubh', label: 'Shubh (male)' },
  { id: 'aditya', label: 'Aditya (male)' },
] as const

function StaticVoiceRow({
  speaker,
  onChange,
}: {
  speaker: string
  onChange: (id: string) => void
}) {
  return (
    <div>
      <label className="text-xs text-karyuk-muted">Phone voice (Sarvam)</label>
      <select
        className="mt-1 w-full rounded-lg border px-2 py-2 text-sm"
        value={speaker}
        onChange={(e) => onChange(e.target.value)}
      >
        {HIRE_VOICES.map((v) => (
          <option key={v.id} value={v.id}>
            {v.label}
          </option>
        ))}
      </select>
      <p className="mt-1 text-[11px] text-karyuk-muted">
        Draft voice — saved with the draft. Live Exotel calls use the published voice. Preview can
        audition another Sarvam voice without changing the line.
      </p>
    </div>
  )
}
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { ApiError, apiFetch, isApiEnabled } from '../../lib/api/client'
import { pushAudit } from '../../lib/localPlatform'
import { syncSessionWithApi } from '../../lib/auth'
import { newId } from '../../lib/id'

type NumberRow = {
  id: string
  e164: string
  dial_national?: string
  status: string
  employee_id: string | null
  inbound_enabled?: boolean
}

type ApiEmployee = {
  id: string
  draft: { brief: string } | null
  status: string
}

type TelephonyStatus = {
  mode: string
  exotel_configured: boolean
  livekit_configured: boolean
  public_api_base_url: string
  exotel_caller_id?: string | null
  exotel_dial_national?: string | null
  exotel_inbound_voice_url?: string
}

type OpsStatus = { telephony: TelephonyStatus }

type MeResponse = {
  workspaces: { id: string; name: string; role: string }[]
}

function hasApiToken() {
  return Boolean(localStorage.getItem('karyuk_access_token'))
}

function normalizePhoneInput(phone: string): string {
  let digits = phone.replace(/\D/g, '')
  if (digits.startsWith('0') && digits.length === 10 && digits.startsWith('040')) {
    digits = `${digits.slice(0, -1)}0${digits.slice(-1)}`
  }
  if (digits.startsWith('91') && digits.length === 12) return `+${digits}`
  if (phone.trim().startsWith('+')) return phone.trim()
  if (digits.startsWith('0') && digits.length === 11) return `+91${digits.slice(1)}`
  if (digits.length === 10 && !digits.startsWith('0')) return `+91${digits}`
  if (digits.startsWith('40') && digits.length === 10) return `+91${digits}`
  if (digits.length > 0) return `+${digits}`
  return phone.trim()
}

function exotelToE164(raw: string | null | undefined): string {
  if (!raw?.trim()) return '+914045900002'
  return normalizePhoneInput(raw.trim())
}

export function NumbersPage() {
  const { user } = useAuth()
  const { prefix: pathPrefix } = useWorkspacePath()
  const { state } = useWorkspace()
  const local = useLocalPlatform()
  const [rows, setRows] = useState<NumberRow[]>([])
  const [e164, setE164] = useState('0404590002')
  const [employeeId, setEmployeeId] = useState('')
  const [apiEmployees, setApiEmployees] = useState<ApiEmployee[]>([])
  const [telephony, setTelephony] = useState<TelephonyStatus | null>(null)
  const [apiWorkspaceId, setApiWorkspaceId] = useState<string | null>(user?.workspaceId ?? null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [registering, setRegistering] = useState(false)
  const [loadingEmployees, setLoadingEmployees] = useState(false)
  const [routeSaving, setRouteSaving] = useState<string | null>(null)

  const apiLinked = isApiEnabled() && hasApiToken()
  const prefix = apiWorkspaceId ? `/v1/workspaces/${apiWorkspaceId}` : pathPrefix

  useEffect(() => {
    setApiWorkspaceId(user?.workspaceId ?? null)
  }, [user?.workspaceId])

  useEffect(() => {
    if (!isApiEnabled()) return
    void (async () => {
      const ops = await apiFetch<OpsStatus>('/v1/ops/status').catch(() => null)
      if (ops?.telephony) {
        setTelephony(ops.telephony)
        if (ops.telephony.exotel_caller_id) {
          setE164((prev) =>
            prev === '+914045900002' || prev === '04045900002' || prev === '0404590002'
              ? exotelToE164(ops.telephony.exotel_caller_id)
              : prev,
          )
        }
      }
      if (!hasApiToken()) return
      const synced = await syncSessionWithApi()
      if (synced?.workspaceId) setApiWorkspaceId(synced.workspaceId)
      else {
        const me = await apiFetch<MeResponse>('/v1/me').catch(() => null)
        if (me?.workspaces[0]?.id) setApiWorkspaceId(me.workspaces[0].id)
      }
      if (prefix) {
        const wsTelephony = await apiFetch<TelephonyStatus>(`${prefix}/telephony/status`).catch(
          () => null,
        )
        if (wsTelephony) setTelephony((t) => ({ ...(t ?? {}), ...wsTelephony } as TelephonyStatus))
      }
    })()
  }, [prefix])

  const reloadEmployees = useCallback(() => {
    if (!apiLinked || !apiWorkspaceId) {
      setLoadingEmployees(false)
      return
    }
    setLoadingEmployees(true)
    return apiFetch<ApiEmployee[]>(`/v1/workspaces/${apiWorkspaceId}/employees`)
      .then((list) => {
        setApiEmployees(list)
        const published = list.filter((e) => e.status === 'published')
        const pick = published[0] ?? list[0]
        if (pick) setEmployeeId((prev) => prev || pick.id)
      })
      .catch(() => setApiEmployees([]))
      .finally(() => setLoadingEmployees(false))
  }, [apiLinked, apiWorkspaceId])

  useEffect(() => {
    void reloadEmployees()
  }, [reloadEmployees])

  const localEmployees = useMemo(
    () =>
      state.employees.map((e) => ({
        id: e.id,
        draft: { brief: e.brief },
        status: e.status ?? 'draft',
      })),
    [state.employees],
  )

  const employeesForSelect = useMemo(() => {
    if (!isApiEnabled()) return localEmployees
    if (apiEmployees.length > 0) return apiEmployees
    if (!apiLinked) return localEmployees
    return apiEmployees
  }, [apiEmployees, apiLinked, localEmployees])

  const publishedEmployees = useMemo(
    () => employeesForSelect.filter((e) => e.status === 'published'),
    [employeesForSelect],
  )

  const load = useCallback(() => {
    if (!apiLinked) {
      setRows(local.state.phoneNumbers)
      return
    }
    if (!prefix) return
    void apiFetch<NumberRow[]>(`${prefix}/phone-numbers`).then(setRows).catch(() => setRows([]))
  }, [apiLinked, prefix, local.state.phoneNumbers])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const first = employeesForSelect[0]
    if (first) setEmployeeId((prev) => prev || first.id)
  }, [employeesForSelect])

  const routingChoices = employeesForSelect

  const needsEmployeePick = routingChoices.length > 0
  const canRegister =
    e164.trim().length > 0 &&
    !registering &&
    !loadingEmployees &&
    (apiLinked ? Boolean(apiWorkspaceId) : true) &&
    (!needsEmployeePick || Boolean(employeeId))

  const registerHint = useMemo(() => {
    if (!isApiEnabled()) return null
    if (!hasApiToken()) {
      return (
        <>
          Your session is browser-only. Reload the page to sync with the API, or register
          below to save locally.
        </>
      )
    }
    if (!apiWorkspaceId) return 'Loading workspace…'
    if (employeesForSelect.length === 0 && !loadingEmployees) {
      return (
        <>
          No employees yet — you can still register the ExoPhone.{' '}
          <Link to="/app" className="font-medium underline">
            Hire one
          </Link>{' '}
          and publish on Team to route inbound calls.
        </>
      )
    }
    if (publishedEmployees.length === 0 && apiLinked) {
      return (
        <>
          No published employee yet —{' '}
          <Link to="/app/team" className="font-medium underline">
            publish on Team
          </Link>{' '}
          for live inbound (you can still register routing now).
        </>
      )
    }
    return null
  }, [
    apiLinked,
    apiWorkspaceId,
    employeeId,
    employeesForSelect.length,
    publishedEmployees.length,
  ])

  const register = async () => {
    setErr(null)
    setMsg(null)
    const raw = e164.trim()
    const normalized =
      raw.startsWith('0') && !raw.startsWith('+') ? raw : normalizePhoneInput(raw)
    if (!normalized || normalized.replace(/\D/g, '').length < 10) {
      setErr('Enter a valid ExoPhone (e.g. 0404590002).')
      return
    }
    if (needsEmployeePick && !employeeId) {
      setErr('Select an employee.')
      return
    }

    setRegistering(true)
    try {
      if (!apiLinked || !prefix) {
        const row: NumberRow = {
          id: newId(),
          e164: normalized,
          status: 'active',
          employee_id: employeeId || null,
          inbound_enabled: true,
        }
        local.update((prev) => ({ ...prev, phoneNumbers: [row, ...prev.phoneNumbers] }))
        pushAudit(local.workspaceId, 'number.registered', normalized)
        setMsg(
          apiLinked
            ? 'Number saved locally (re-authenticate to persist to API).'
            : 'Number saved locally.',
        )
        load()
        return
      }

      const payload: { e164: string; employee_id?: string } = { e164: normalized }
      if (employeeId) payload.employee_id = employeeId
      const res = await apiFetch<{ id: string; updated?: boolean }>(`${prefix}/phone-numbers`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setMsg(res.updated ? 'Number updated with new routing.' : 'Number registered in workspace.')
      setE164(normalized)
      load()
    } catch (e) {
      const text =
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : 'Could not register number'
      setErr(text)
    } finally {
      setRegistering(false)
    }
  }

  const updateRoute = async (row: NumberRow, newEmployeeId: string) => {
    if (!apiLinked || !prefix || !newEmployeeId) return
    setRouteSaving(row.id)
    setErr(null)
    try {
      await apiFetch(`${prefix}/phone-numbers/${row.id}/route`, {
        method: 'PUT',
        body: JSON.stringify({ e164: row.e164, employee_id: newEmployeeId }),
      })
      setMsg(`Updated routing for ${row.e164}.`)
      load()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not update routing')
    } finally {
      setRouteSaving(null)
    }
  }

  const copyInboundUrl = async () => {
    const url = telephony?.exotel_inbound_voice_url
    if (!url) {
      setErr('Inbound URL not available — check API .env PUBLIC_API_BASE_URL.')
      return
    }
    try {
      await navigator.clipboard.writeText(url)
      setMsg('Exotel inbound webhook URL copied.')
    } catch {
      setErr(url)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">Numbers & channels</h1>
      <p className="text-sm text-karyuk-muted">
        Register the phone line your customers see and route it to an AI employee for{' '}
        <strong>inbound</strong> calls (dial your ExoPhone — no outbound KYC).
      </p>

      {telephony?.exotel_inbound_voice_url && (
        <section className="rounded-2xl border bg-white p-4 text-sm">
          <h2 className="font-semibold text-karyuk-ink">Inbound webhook (Exotel applet)</h2>
          {(telephony.exotel_dial_national || telephony.exotel_caller_id) && (
            <p className="mt-1 text-sm">
              Test call: dial{' '}
              <strong className="font-mono">{telephony.exotel_dial_national ?? telephony.exotel_caller_id}</strong>{' '}
              from your mobile (local 040… format — do not dial +91).
            </p>
          )}
          <p className="mt-1 break-all font-mono text-xs text-karyuk-muted">
            {telephony.exotel_inbound_voice_url}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void copyInboundUrl()}
              className="rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-karyuk-panel"
            >
              Copy URL
            </button>
            {telephony.exotel_caller_id && (
              <button
                type="button"
                onClick={() => setE164(exotelToE164(telephony.exotel_caller_id))}
                className="rounded-full border px-3 py-1.5 text-xs font-medium hover:bg-karyuk-panel"
              >
                Use ExoPhone from .env
              </button>
            )}
          </div>
        </section>
      )}

      {registerHint && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {registerHint}
        </p>
      )}

      <div className="space-y-2 rounded-2xl border bg-white p-4">
        <label className="text-xs font-medium text-karyuk-muted">ExoPhone (local 040… or E.164)</label>
        <input
          className="w-full rounded border px-2 py-2 text-sm"
          value={e164}
          onChange={(e) => setE164(e.target.value)}
          onBlur={() => {
            const raw = e164.trim()
            if (raw.startsWith('0') && !raw.startsWith('+')) {
              setE164(raw)
              return
            }
            setE164(normalizePhoneInput(raw))
          }}
          placeholder="0404590002"
        />
        <label className="text-xs font-medium text-karyuk-muted">Route to employee</label>
        <select
          className="w-full rounded border px-2 py-2 text-sm"
          value={employeeId}
          onChange={(e) => setEmployeeId(e.target.value)}
          disabled={loadingEmployees && apiLinked}
        >
          <option value="">
            {loadingEmployees && apiLinked ? 'Loading employees…' : 'Select employee'}
          </option>
          {routingChoices.map((e) => (
            <option key={e.id} value={e.id}>
              {(e.draft?.brief ?? 'Employee').slice(0, 40)}… ({e.status})
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void register()}
          disabled={!canRegister}
          className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm font-medium text-white hover:bg-karyuk-green disabled:cursor-not-allowed disabled:opacity-40"
        >
          {registering ? 'Saving…' : 'Register number'}
        </button>
        {msg && <p className="text-sm text-karyuk-green-dark">{msg}</p>}
        {err && <p className="text-sm text-red-600">{err}</p>}
      </div>

      <section className="rounded-2xl border border-dashed border-karyuk-border bg-karyuk-panel/40 p-4 text-sm text-karyuk-muted">
        <h2 className="font-semibold text-karyuk-ink">Exotel (live telephony)</h2>
        <ol className="mt-2 list-decimal space-y-1 pl-5">
          <li>
            ExoPhone{' '}
            <strong>{telephony?.exotel_dial_national ?? telephony?.exotel_caller_id ?? '0404590002'}</strong>{' '}
            (dial locally — not +91) matches{' '}
            <code className="text-xs">EXOTEL_CALLER_ID</code> in API <code className="text-xs">.env</code>.
          </li>
          <li>Register that number here and assign an employee (publish on Team for live calls).</li>
          <li>Paste the inbound webhook URL into the Exotel ExoPhone applet (GET or POST).</li>
          <li>
            Run <code className="text-xs">.\scripts\run-voice-agent.ps1</code>, then call the ExoPhone from your
            mobile.
          </li>
        </ol>
      </section>

      <ul className="space-y-2">
        {rows.length === 0 && (
          <li className="text-sm text-karyuk-muted">No numbers registered yet.</li>
        )}
        {rows.map((r) => (
          <li key={r.id} className="rounded-xl border bg-white px-4 py-3 text-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <span>
                <span title={r.e164}>{r.dial_national ?? r.e164}</span> · {r.status}
                {r.inbound_enabled === false ? ' · inbound off' : ''}
              </span>
              {apiLinked && prefix && employeesForSelect.length > 0 && (
                <div className="flex items-center gap-2">
                  <select
                    className="rounded border px-2 py-1 text-xs"
                    defaultValue={r.employee_id ?? ''}
                    onChange={(e) => void updateRoute(r, e.target.value)}
                    disabled={routeSaving === r.id}
                  >
                    <option value="">Unassigned</option>
                    {employeesForSelect.map((e) => (
                      <option key={e.id} value={e.id}>
                        {(e.draft?.brief ?? 'Employee').slice(0, 24)}…
                      </option>
                    ))}
                  </select>
                  {routeSaving === r.id && (
                    <span className="text-xs text-karyuk-muted">Saving…</span>
                  )}
                </div>
              )}
              {!apiLinked && (
                <span className="text-xs text-karyuk-muted">
                  employee {r.employee_id ?? 'unassigned'}
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
import { newId } from './id'

export type LocalLead = {
  id: string
  name?: string
  phone_e164: string
  status: string
}

export type LocalCall = {
  id: string
  direction: string
  outcome: string
  duration_seconds: number
  cost_paise: number
  transcript?: string
  summary?: string
  employee_id?: string
  lead_id?: string
  created_at?: string
  provider?: string
}

export type LocalCampaign = { id: string; name: string; status: string }

export type LocalPhoneNumber = {
  id: string
  e164: string
  status: string
  employee_id: string | null
}

export type LocalPlatformState = {
  leads: LocalLead[]
  calls: LocalCall[]
  campaigns: LocalCampaign[]
  phoneNumbers: LocalPhoneNumber[]
  timezone: string
  retention_days: number
  knowledge: { id: string; title: string; content: string }[]
  audit: { action: string; summary: string }[]
  walletTransactions: { entry_type: string; amount_paise: number }[]
  integrations: { integration_type: string; status: string }[]
  webhookUrl: string | null
  ingressSecret: string
}

const storageKey = (workspaceId: string) => `karyuk_platform_${workspaceId}`

const defaultState = (): LocalPlatformState => ({
  leads: [
    {
      id: 'local-lead-demo',
      name: 'Priya Sharma',
      phone_e164: '+919876543210',
      status: 'active',
    },
  ],
  calls: [
    {
      id: 'local-call-demo',
      direction: 'outbound',
      outcome: 'completed',
      duration_seconds: 94,
      cost_paise: 420,
      transcript:
        'Agent: Hi Priya, this is Karyuk calling about your test drive.\nPriya: Tomorrow 4pm works.\nAgent: Booked — see you then.',
      summary: 'Test drive scheduled for tomorrow 4pm.',
    },
  ],
  campaigns: [],
  phoneNumbers: [],
  timezone: 'Asia/Kolkata',
  retention_days: 90,
  knowledge: [],
  audit: [{ action: 'workspace.created', summary: 'Local preview workspace' }],
  walletTransactions: [],
  integrations: [],
  webhookUrl: null,
  ingressSecret: 'local_dev_secret_preview_only',
})

export function getPlatform(workspaceId: string): LocalPlatformState {
  try {
    const raw = localStorage.getItem(storageKey(workspaceId))
    if (!raw) return defaultState()
    return { ...defaultState(), ...(JSON.parse(raw) as LocalPlatformState) }
  } catch {
    return defaultState()
  }
}

export function setPlatform(workspaceId: string, state: LocalPlatformState) {
  localStorage.setItem(storageKey(workspaceId), JSON.stringify(state))
}

export function patchPlatform(
  workspaceId: string,
  updater: (prev: LocalPlatformState) => LocalPlatformState,
): LocalPlatformState {
  const next = updater(getPlatform(workspaceId))
  setPlatform(workspaceId, next)
  return next
}

export function pushAudit(
  workspaceId: string,
  action: string,
  summary: string,
): LocalPlatformState {
  return patchPlatform(workspaceId, (prev) => ({
    ...prev,
    audit: [{ action, summary }, ...prev.audit].slice(0, 50),
  }))
}

export function analyticsFromCalls(calls: LocalCall[]) {
  const attempted = calls.length
  const connected = calls.filter((c) => c.outcome === 'completed').length
  return {
    attempted,
    connected,
    completion_rate: attempted ? connected / attempted : 0,
  }
}

export function resolveLocalCallOutcome(row: LocalCall): LocalCall {
  if (row.outcome === 'completed' || row.outcome === 'failed') return row
  const started = row.created_at ? new Date(row.created_at).getTime() : Date.now()
  const age = Date.now() - started
  if (age < 2500) return { ...row, outcome: 'dialing', provider: 'local' }
  if (age < 5000) return { ...row, outcome: 'ringing', provider: 'local' }
  if (age < 7500) return { ...row, outcome: 'connected', provider: 'local' }
  return {
    ...row,
    outcome: 'completed',
    duration_seconds: 72,
    cost_paise: 350,
    transcript: row.transcript ?? `Simulated call to lead (${row.lead_id ?? '—'}).`,
    summary: row.summary ?? 'Local preview — connect Exotel for live calls.',
    provider: 'local',
  }
}

export function simulateOutboundCall(
  workspaceId: string,
  input: { employee_id?: string; lead_id?: string; phone?: string; name?: string },
): { call_id: string; outcome: string } {
  const callId = newId()
  patchPlatform(workspaceId, (prev) => ({
    ...prev,
    calls: [
      {
        id: callId,
        direction: 'outbound',
        outcome: 'dialing',
        duration_seconds: 0,
        cost_paise: 0,
        employee_id: input.employee_id,
        lead_id: input.lead_id,
        created_at: new Date().toISOString(),
        provider: 'local',
        transcript: `Simulated call to ${input.name ?? 'lead'} (${input.phone ?? '—'}).`,
      },
      ...prev.calls,
    ],
    audit: [
      { action: 'call.completed', summary: `Call ${callId.slice(0, 8)}…` },
      ...prev.audit,
    ].slice(0, 50),
  }))
  return { call_id: callId, outcome: 'dialing' }
}
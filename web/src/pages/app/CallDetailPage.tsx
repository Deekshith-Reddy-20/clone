import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useLocalPlatform } from '../../hooks/useLocalPlatform'
import { useWorkspacePath } from '../../hooks/useWorkspacePath'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import { providerLabel } from '../../lib/providerLabel'

type CallDetail = {
  id?: string
  lead_id?: string | null
  transcript?: string | null
  summary?: string | null
  captured_fields?: Record<string, unknown>
  outcome?: string
  disposition?: string | null
  duration_seconds?: number
  provider?: string | null
  provider_call_sid?: string | null
  recording_url?: string | null
  is_test?: boolean
  started_at?: string | null
  ended_at?: string | null
  created_at?: string | null
}

export function CallDetailPage() {
  const { callId } = useParams()
  const { prefix } = useWorkspacePath()
  const local = useLocalPlatform()
  const [detail, setDetail] = useState<CallDetail | null>(null)

  useEffect(() => {
    if (!callId) return
    if (!isApiEnabled()) {
      const call = local.state.calls.find((c) => c.id === callId)
      if (call) {
        setDetail({
          transcript: call.transcript,
          summary: call.summary,
        })
      } else {
        setDetail(null)
      }
      return
    }
    if (!prefix) return
    void apiFetch<CallDetail>(`${prefix}/calls/${callId}`).then(setDetail)
  }, [prefix, callId, local.state.calls])

  if (!detail) {
    return <p className="text-sm text-karyuk-muted">Loading…</p>
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Link to="/app/conversations" className="text-sm text-karyuk-muted">
        ← Back
      </Link>
      <h1 className="text-2xl font-semibold">Call detail</h1>
      <div className="rounded-2xl border bg-white p-4 text-sm space-y-1">
        <p>
          Outcome: {detail.outcome || '—'}
          {detail.disposition ? ` · ${detail.disposition}` : ''}
          {detail.is_test ? ' · TEST' : ''}
        </p>
        <p className="text-karyuk-muted">
          Channel: {providerLabel(detail.provider) || '—'} · Duration: {detail.duration_seconds ?? 0}s
          {detail.captured_fields?.voice_build_sha
            ? ` · build ${String(detail.captured_fields.voice_build_sha)}`
            : ''}
        </p>
        {detail.provider_call_sid && (
          <p className="text-xs text-karyuk-muted">External ID: {detail.provider_call_sid}</p>
        )}
        {detail.captured_fields?.vad_engine ? (
          <p className="text-xs text-karyuk-muted">
            VAD: {String(detail.captured_fields.vad_engine)} · barge-in{' '}
            {String(detail.captured_fields.voice_barge_in ?? 'off')}
          </p>
        ) : null}
        {detail.lead_id && (
          <Link to="/app/leads" className="text-karyuk-green-dark">
            Linked lead {detail.lead_id.slice(0, 8)}…
          </Link>
        )}
        {detail.recording_url && (
          <a
            href={detail.recording_url}
            target="_blank"
            rel="noreferrer"
            className="block text-karyuk-green-dark underline"
          >
            Open recording
          </a>
        )}
      </div>
      {detail.captured_fields?.voice_turn_metrics ? (
        <div className="rounded-2xl border bg-white p-4 text-sm">
          <p className="font-semibold">Turn latency</p>
          <ul className="mt-2 space-y-1 text-xs font-mono">
            {(detail.captured_fields.voice_turn_metrics as Array<Record<string, unknown>>).map(
              (row, i) => (
                <li key={i}>
                  #{String(row.turn)} e2e={String(row.e2e_ms)}ms stt={String(row.stt_final_ms)}ms
                  llm={String(row.llm_ttft_ms)}ms tts={String(row.tts_ttfb_ms)}ms provider=
                  {String(row.provider)} barge={String(row.barge_in)}
                </li>
              ),
            )}
          </ul>
          {detail.captured_fields.voice_latency_summary ? (
            <p className="mt-2 text-xs text-karyuk-muted">
              p50 e2e: {String((detail.captured_fields.voice_latency_summary as Record<string, number>).e2e_p50_ms)}ms
              · p95:{' '}
              {String((detail.captured_fields.voice_latency_summary as Record<string, number>).e2e_p95_ms)}ms
            </p>
          ) : null}
        </div>
      ) : null}
      {detail.captured_fields?.voice_turn_trace ? (
        <div className="rounded-2xl border bg-white p-4 text-sm overflow-x-auto">
          <p className="font-semibold">Turn source</p>
          <table className="mt-2 w-full text-xs">
            <thead>
              <tr className="text-left text-karyuk-muted">
                <th className="pr-2">#</th>
                <th className="pr-2">source</th>
                <th className="pr-2">provider</th>
                <th className="pr-2">guard</th>
                <th>caller / agent</th>
              </tr>
            </thead>
            <tbody>
              {(detail.captured_fields.voice_turn_trace as Array<Record<string, unknown>>).map(
                (row) => (
                  <tr key={String(row.turn)} className="border-t border-karyuk-border/40">
                    <td className="py-1 pr-2 font-mono">{String(row.turn)}</td>
                    <td className="py-1 pr-2 font-mono">{String(row.source)}</td>
                    <td className="py-1 pr-2 font-mono text-karyuk-muted">
                      {row.provider != null ? String(row.provider) : '—'}
                    </td>
                    <td className="py-1 pr-2 font-mono text-karyuk-muted">
                      {Array.isArray(row.guard_actions)
                        ? (row.guard_actions as string[]).join(', ')
                        : '—'}
                    </td>
                    <td className="py-1">
                      <span className="text-karyuk-muted">C:</span> {String(row.caller).slice(0, 80)}
                      <br />
                      <span className="text-karyuk-muted">A:</span> {String(row.agent).slice(0, 120)}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="whitespace-pre-wrap rounded-2xl border bg-white p-4 text-sm">
        {String(detail.transcript ?? 'No transcript yet.')}
      </p>
      <p className="text-sm text-karyuk-muted">{String(detail.summary ?? '')}</p>
      {detail.captured_fields && Object.keys(detail.captured_fields).length > 0 && (
        <pre className="overflow-auto rounded-2xl border bg-white p-4 text-xs">
          {JSON.stringify(detail.captured_fields, null, 2)}
        </pre>
      )}
    </div>
  )
}

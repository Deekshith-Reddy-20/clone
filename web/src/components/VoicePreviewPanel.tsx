import { Mic, MicOff, Phone, PhoneOff, Volume2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, isApiEnabled, wsBaseFromApi } from '../lib/api/client'
import {
  acquireMicrophoneStream,
  micSupportState,
  suggestedSecureVoiceUrl,
} from '../lib/microphone'

type VoiceDef = {
  id: string
  label: string
  gender: 'female' | 'male'
  hint: string
}

type TranscriptLine = {
  id: string
  role: 'caller' | 'agent' | 'system'
  text: string
}

const FALLBACK_VOICES: VoiceDef[] = [
  { id: 'priya', label: 'Priya', gender: 'female', hint: 'Warm, clear' },
  { id: 'neha', label: 'Neha', gender: 'female', hint: 'Conversational' },
  { id: 'shubh', label: 'Shubh', gender: 'male', hint: 'Default phone voice' },
  { id: 'aditya', label: 'Aditya', gender: 'male', hint: 'Professional' },
]

function wsUrl(path: string): string {
  const base = wsBaseFromApi()
  if (base) return `${base}${path}`
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${path}`
  }
  return ''
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

function bytesToB64(bytes: ArrayBuffer): string {
  let binary = ''
  const view = new Uint8Array(bytes)
  for (let i = 0; i < view.length; i++) binary += String.fromCharCode(view[i])
  return btoa(binary)
}

function downsampleTo8k(input: Float32Array, inputRate: number): Float32Array {
  const outRate = 8000
  if (inputRate === outRate) return input
  const ratio = inputRate / outRate
  const len = Math.floor(input.length / ratio)
  const out = new Float32Array(len)
  for (let i = 0; i < len; i++) out[i] = input[Math.floor(i * ratio)]
  return out
}

function floatToPcm16(input: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(input.length * 2)
  const view = new DataView(buf)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return buf
}

type Props = {
  workspaceId: string
  employeeId: string
  disabled?: boolean
}

export function VoicePreviewPanel({ workspaceId, employeeId, disabled }: Props) {
  const [voices, setVoices] = useState<VoiceDef[]>(FALLBACK_VOICES)
  const [speaker, setSpeaker] = useState('shubh')
  const [status, setStatus] = useState<'idle' | 'connecting' | 'live' | 'error'>('idle')
  const [statusDetail, setStatusDetail] = useState('')
  const [micReady, setMicReady] = useState(false)
  const [secureVoiceUrl, setSecureVoiceUrl] = useState<string | undefined>(() =>
    suggestedSecureVoiceUrl(),
  )
  const [lines, setLines] = useState<TranscriptLine[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const streamSid = useRef('browser-preview')
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const agentSpeakingRef = useRef(false)
  const agentQuietUntilRef = useRef(0)
  const playQueueRef = useRef<Promise<void>>(Promise.resolve())
  const activeRef = useRef(false)
  const micReadyRef = useRef(false)
  const pcmAccum = useRef(new Float32Array(0))
  const micRing = useRef(new Float32Array(0))
  const sendTimer = useRef<number | null>(null)
  const MAX_MIC_RING_SAMPLES = 16_000

  useEffect(() => {
    if (!isApiEnabled() || !workspaceId || !employeeId) return
    void apiFetch<{
      draft?: { tts_speaker?: string } | null
      published_snapshot?: { tts_speaker?: string } | null
    }>(`/v1/workspaces/${workspaceId}/employees/${employeeId}`)
      .then((emp) => {
        const pub = emp.published_snapshot?.tts_speaker
        const draft = emp.draft?.tts_speaker
        if (pub) setSpeaker(pub)
        else if (draft) setSpeaker(draft)
      })
      .catch(() => {})
  }, [workspaceId, employeeId])

  useEffect(() => {
    if (!isApiEnabled() || !workspaceId) return
    void apiFetch<VoiceDef[]>(`/v1/workspaces/${workspaceId}/voice-preview/voices`)
      .then(setVoices)
      .catch(() => setVoices(FALLBACK_VOICES))
  }, [workspaceId])

  const pushLine = useCallback((role: TranscriptLine['role'], text: string) => {
    setLines((prev) => [
      ...prev,
      { id: `${Date.now()}-${prev.length}`, role, text },
    ])
  }, [])

  const playPcm8k = useCallback((pcm: Uint8Array) => {
    const ctx = audioCtxRef.current
    if (!ctx || pcm.length < 2) return
    const samples = new Int16Array(pcm.buffer, pcm.byteOffset, Math.floor(pcm.byteLength / 2))
    const audioBuf = ctx.createBuffer(1, samples.length, 8000)
    const ch = audioBuf.getChannelData(0)
    for (let i = 0; i < samples.length; i++) ch[i] = samples[i] / 32768
    const playMs = (samples.length / 8000) * 1000 + 320
    playQueueRef.current = playQueueRef.current.then(
      () =>
        new Promise<void>((resolve) => {
          agentSpeakingRef.current = true
          agentQuietUntilRef.current = Math.max(
            agentQuietUntilRef.current,
            performance.now() + playMs,
          )
          const src = ctx.createBufferSource()
          src.buffer = audioBuf
          src.connect(ctx.destination)
          src.onended = () => {
            const tail = performance.now() + 320
            agentQuietUntilRef.current = Math.max(agentQuietUntilRef.current, tail)
            window.setTimeout(() => {
              if (performance.now() >= agentQuietUntilRef.current) {
                agentSpeakingRef.current = false
              }
            }, 340)
            resolve()
          }
          src.start()
        }),
    )
  }, [])

  const setupMicPipeline = useCallback(async () => {
    const support = micSupportState()
    if (!support.ok) {
      setMicReady(false)
      setSecureVoiceUrl(support.secureUrl ?? suggestedSecureVoiceUrl())
      setStatusDetail(support.detail)
      return
    }
    try {
      const stream = await acquireMicrophoneStream()
      micStreamRef.current = stream
      micReadyRef.current = true
      setMicReady(true)
      setSecureVoiceUrl(undefined)
      const ctx = audioCtxRef.current ?? new AudioContext()
      audioCtxRef.current = ctx
      if (ctx.state === 'suspended') await ctx.resume()

      const source = ctx.createMediaStreamSource(stream)
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor
      processor.onaudioprocess = (ev) => {
        if (!activeRef.current) return
        const input = ev.inputBuffer.getChannelData(0)
        const chunk = downsampleTo8k(input, ctx.sampleRate)
        const gated = performance.now() < agentQuietUntilRef.current
        if (gated) {
          const prev = micRing.current
          const merged = new Float32Array(prev.length + chunk.length)
          merged.set(prev)
          merged.set(chunk, prev.length)
          if (merged.length > MAX_MIC_RING_SAMPLES) {
            micRing.current = merged.slice(-MAX_MIC_RING_SAMPLES)
          } else {
            micRing.current = merged
          }
          return
        }
        if (micRing.current.length > 0) {
          const tail = micRing.current
          micRing.current = new Float32Array(0)
          const prev = pcmAccum.current
          const merged = new Float32Array(prev.length + tail.length + chunk.length)
          merged.set(prev)
          merged.set(tail, prev.length)
          merged.set(chunk, prev.length + tail.length)
          pcmAccum.current = merged
        } else {
          const prev = pcmAccum.current
          const merged = new Float32Array(prev.length + chunk.length)
          merged.set(prev)
          merged.set(chunk, prev.length)
          pcmAccum.current = merged
        }
      }
      const gain = ctx.createGain()
      gain.gain.value = 2.4
      source.connect(gain)
      gain.connect(processor)
      const mute = ctx.createGain()
      mute.gain.value = 0
      processor.connect(mute)
      mute.connect(ctx.destination)
      setStatusDetail('Live — speak after the greeting (like a phone call).')
    } catch (e) {
      setMicReady(false)
      const msg = e instanceof Error ? e.message : 'Microphone permission denied'
      setStatusDetail(`Could not open microphone — ${msg}`)
    }
  }, [])

  const stopSession = useCallback(() => {
    activeRef.current = false
    if (sendTimer.current) {
      window.clearInterval(sendTimer.current)
      sendTimer.current = null
    }
    processorRef.current?.disconnect()
    processorRef.current = null
    micStreamRef.current?.getTracks().forEach((t) => t.stop())
    micStreamRef.current = null
    if (wsRef.current) {
      try {
        wsRef.current.send(JSON.stringify({ event: 'stop' }))
        wsRef.current.close()
      } catch {
        /* ignore */
      }
    }
    wsRef.current = null
    micReadyRef.current = false
    micRing.current = new Float32Array(0)
    setMicReady(false)
    setSecureVoiceUrl(suggestedSecureVoiceUrl())
    setStatus('idle')
    setStatusDetail('')
    pushLine('system', 'Session ended.')
  }, [pushLine])

  const startSession = useCallback(async () => {
    if (!isApiEnabled() || disabled) return
    const mic = micSupportState()
    if (!mic.ok && mic.reason === 'insecure') {
      setSecureVoiceUrl(mic.secureUrl ?? suggestedSecureVoiceUrl())
      setStatus('error')
      setStatusDetail(mic.detail)
      return
    }
    setStatus('connecting')
    setLines([])
    setStatusDetail('Starting same path as your business line…')
    try {
      const session = await apiFetch<{
        call_id: string
        speaker: string
        websocket_path: string
        worker_build_sha?: string
        employee_snapshot_revision?: string
        employee_version_number?: string
        speech_stack?: string
        knowledge_state?: string
        published_speaker?: string
        published_mode?: string
        knowledge_chars?: number
        preview_path?: string
        sarvam_ready?: boolean
        sarvam_status?: string
      }>(`/v1/workspaces/${workspaceId}/employees/${employeeId}/voice-preview`, {
        method: 'POST',
        body: JSON.stringify({ speaker }),
      })
      const rev = session.employee_snapshot_revision
        ? ` · rev ${session.employee_snapshot_revision.slice(0, 8)}`
        : ''
      const build = session.worker_build_sha ? ` · worker ${session.worker_build_sha}` : ''
      const pub = session.published_speaker
        ? session.speaker !== session.published_speaker
          ? ` · testing ${session.speaker} (published: ${session.published_speaker})`
          : ` · voice ${session.speaker}`
        : ` · voice ${session.speaker}`
      const ver = session.employee_version_number
        ? ` · v${session.employee_version_number}`
        : ''
      const know =
        session.knowledge_state === 'draft'
          ? `draft settings (rev ${session.employee_snapshot_revision ?? '?'})`
          : session.knowledge_state === 'published'
            ? `published knowledge (${session.knowledge_chars ?? 0} chars)`
            : `${session.knowledge_state ?? 'draft'} snapshot`
      const mode = session.published_mode
        ? ` · mode ${session.published_mode}`
        : ''
      pushLine(
        'system',
        `Voice test · ${know} · ${session.speech_stack ?? 'sarvam'}${mode}${pub}${rev}${ver}${build}`,
      )
      if (session.preview_path) {
        pushLine('system', session.preview_path)
      }
      if (session.sarvam_ready === false && session.sarvam_status) {
        pushLine('system', session.sarvam_status)
        setStatusDetail(session.sarvam_status)
      }

      const ctx = new AudioContext()
      audioCtxRef.current = ctx
      if (ctx.state === 'suspended') await ctx.resume()

      const url = wsUrl(session.websocket_path)
      const ws = new WebSocket(url)
      wsRef.current = ws
      activeRef.current = true

      ws.onopen = () => {
        ws.send(JSON.stringify({ event: 'connected' }))
        ws.send(
          JSON.stringify({
            event: 'start',
            stream_sid: streamSid.current,
            start: { mediaFormat: { encoding: 'audio/l16', sampleRate: 8000 } },
          }),
        )
        setStatus('live')
        setStatusDetail('Connecting audio…')
        void setupMicPipeline()
      }

      ws.onmessage = (ev) => {
        let msg: {
          event?: string
          media?: { payload?: string }
          transcript?: { role?: string; text?: string }
        }
        try {
          msg = JSON.parse(ev.data as string)
        } catch {
          return
        }
        if (msg.event === 'media' && msg.media?.payload) {
          playPcm8k(b64ToBytes(msg.media.payload))
        }
        if (msg.event === 'transcript' && msg.transcript?.text) {
          const role = msg.transcript.role === 'agent' ? 'agent' : 'caller'
          pushLine(role, msg.transcript.text)
        }
        if (msg.event === 'clear') {
          agentSpeakingRef.current = false
        }
      }

      ws.onerror = () => {
        setStatus('error')
        setStatusDetail('WebSocket error — check API URL and mic permission.')
      }

      ws.onclose = () => {
        if (!activeRef.current) return
        setStatus('error')
        setStatusDetail((prev) =>
          prev && !prev.includes('Listen-only')
            ? `${prev} Connection closed.`
            : 'Connection closed — retry voice test.',
        )
        stopSession()
      }

      const chunkSamples = 2400
      sendTimer.current = window.setInterval(() => {
        const wsOk = wsRef.current?.readyState === WebSocket.OPEN
        if (!wsOk || !activeRef.current || !micReadyRef.current) return
        if (performance.now() < agentQuietUntilRef.current) return
        const acc = pcmAccum.current
        if (acc.length < chunkSamples) return
        const slice = acc.slice(0, chunkSamples)
        pcmAccum.current = acc.slice(chunkSamples)
        const pcm = floatToPcm16(slice)
        ws.send(
          JSON.stringify({
            event: 'media',
            stream_sid: streamSid.current,
            media: {
              track: 'inbound',
              payload: bytesToB64(pcm),
            },
          }),
        )
      }, 100)
    } catch (e) {
      setStatus('error')
      setStatusDetail(e instanceof Error ? e.message : 'Could not start preview')
      stopSession()
    }
  }, [disabled, employeeId, playPcm8k, pushLine, setupMicPipeline, speaker, stopSession, workspaceId])

  const females = voices.filter((v) => v.gender === 'female')
  const males = voices.filter((v) => v.gender === 'male')

  return (
    <section className="space-y-4 rounded-xl border border-karyuk-mint/40 bg-gradient-to-b from-karyuk-mint-soft/40 to-white p-4">
      <div className="flex items-start gap-2">
        <Volume2 className="mt-0.5 h-5 w-5 text-karyuk-green-dark" aria-hidden />
        <div>
          <h2 className="text-sm font-semibold text-karyuk-ink">Test with your information</h2>
          <p className="mt-1 text-xs text-karyuk-muted">
            Real-time voice — draft settings over WSS (Saaras v4 + Bulbul v4 Flash). Uses your mic in the
            browser; live Exotel uses the published snapshot for the assigned number.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-medium text-karyuk-ink">Female voices</p>
        <div className="grid grid-cols-2 gap-2">
          {females.map((v) => (
            <VoiceChip
              key={v.id}
              voice={v}
              selected={speaker === v.id}
              disabled={status === 'live' || status === 'connecting'}
              onPick={() => setSpeaker(v.id)}
            />
          ))}
        </div>
        <p className="text-xs font-medium text-karyuk-ink">Male voices</p>
        <div className="grid grid-cols-2 gap-2">
          {males.map((v) => (
            <VoiceChip
              key={v.id}
              voice={v}
              selected={speaker === v.id}
              disabled={status === 'live' || status === 'connecting'}
              onPick={() => setSpeaker(v.id)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {status === 'idle' || status === 'error' ? (
          <button
            type="button"
            disabled={!isApiEnabled() || disabled}
            onClick={() => void startSession()}
            className="inline-flex items-center gap-2 rounded-full bg-karyuk-green-dark px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            <Phone className="h-4 w-4" aria-hidden />
            Start voice test
          </button>
        ) : (
          <button
            type="button"
            onClick={() => stopSession()}
            className="inline-flex items-center gap-2 rounded-full border border-rose-300 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-800"
          >
            <PhoneOff className="h-4 w-4" aria-hidden />
            End test
          </button>
        )}
        {status === 'live' && micReady && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-2 text-xs font-medium text-emerald-800">
            <Mic className="h-3.5 w-3.5 animate-pulse" aria-hidden />
            Mic on — listening
          </span>
        )}
        {status === 'live' && !micReady && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-2 text-xs font-medium text-amber-900">
            <MicOff className="h-3.5 w-3.5" aria-hidden />
            Agent audio only
          </span>
        )}
        {(status === 'connecting' || agentSpeakingRef.current) && status !== 'live' && (
          <span className="text-xs text-karyuk-muted">
            <MicOff className="inline h-3.5 w-3.5" aria-hidden /> Setting up…
          </span>
        )}
      </div>

      {secureVoiceUrl && status !== 'live' ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950">
          <p className="font-medium">Two-way voice needs HTTPS</p>
          <p className="mt-1 text-amber-900">
            Plain <code className="text-[11px]">http://</code> blocks the microphone in Chrome and
            Safari. Open the secure dev URL (trust the certificate once), then start the voice test.
          </p>
          <a
            href={secureVoiceUrl}
            className="mt-2 inline-flex rounded-full bg-amber-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-950"
          >
            Open secure page
          </a>
          <p className="mt-2 break-all font-mono text-[10px] text-amber-900">{secureVoiceUrl}</p>
        </div>
      ) : null}

      {statusDetail ? <p className="text-xs text-karyuk-muted">{statusDetail}</p> : null}

      <ul className="max-h-52 space-y-2 overflow-y-auto rounded-lg border border-karyuk-border bg-white p-3 text-sm">
        {lines.length === 0 ? (
          <li className="text-center text-xs text-karyuk-muted">
            Transcript appears here after the greeting.
          </li>
        ) : (
          lines.map((line) => (
            <li
              key={line.id}
              className={
                line.role === 'agent'
                  ? 'rounded-lg bg-karyuk-mint-soft/70 px-2 py-1.5 text-karyuk-ink'
                  : line.role === 'caller'
                    ? 'rounded-lg bg-karyuk-panel px-2 py-1.5'
                    : 'text-xs italic text-karyuk-muted'
              }
            >
              {line.role === 'agent' && <span className="text-[10px] font-semibold">Agent · </span>}
              {line.role === 'caller' && <span className="text-[10px] font-semibold">You · </span>}
              {line.text}
            </li>
          ))
        )}
      </ul>

      {!isApiEnabled() && (
        <p className="text-xs text-amber-800">Set VITE_API_BASE_URL to enable live voice test.</p>
      )}
    </section>
  )
}

function VoiceChip({
  voice,
  selected,
  disabled,
  onPick,
}: {
  voice: VoiceDef
  selected: boolean
  disabled: boolean
  onPick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onPick}
      className={`rounded-xl border px-3 py-2 text-left text-xs transition-colors ${
        selected
          ? 'border-karyuk-mint bg-karyuk-mint-soft ring-1 ring-karyuk-mint'
          : 'border-karyuk-border bg-white hover:bg-karyuk-panel'
      } ${disabled ? 'opacity-60' : ''}`}
    >
      <span className="font-semibold text-karyuk-ink">{voice.label}</span>
      <span className="mt-0.5 block text-[10px] text-karyuk-muted">{voice.hint}</span>
    </button>
  )
}
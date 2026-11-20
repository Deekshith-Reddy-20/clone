import { Headphones, Pause, Play, User } from 'lucide-react'
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'

const callPath = [
  { step: '1', title: 'Answer', subtitle: 'Incoming call' },
  { step: '2', title: 'Understand', subtitle: 'The request' },
  { step: '3', title: 'Check', subtitle: 'If connected' },
  { step: '4', title: 'Confirm', subtitle: 'If accepted' },
  { step: '5', title: 'Hand off', subtitle: 'When needed' },
]

const script = [
  {
    role: 'caller' as const,
    time: '00:08',
    message: 'Hi, do you have a deluxe room available this Saturday?',
    step: 2,
  },
  {
    role: 'agent' as const,
    time: '00:10',
    message: 'I can check availability once a system is connected.',
    step: 3,
  },
  {
    role: 'caller' as const,
    time: '00:21',
    message: 'Perfect, what’s the rate for two nights?',
    step: 2,
  },
]

export type SampleCallHandle = {
  play: () => void
}

type SampleCallPanelProps = {
  playToken?: number
}

export const SampleCallPanel = forwardRef<SampleCallHandle, SampleCallPanelProps>(
  function SampleCallPanel({ playToken = 0 }, ref) {
    const [visibleCount, setVisibleCount] = useState(0)
    const [activeStep, setActiveStep] = useState(1)
    const [playing, setPlaying] = useState(false)
    const [showExtras, setShowExtras] = useState(false)
    const timersRef = useRef<number[]>([])

    const clearTimers = useCallback(() => {
      timersRef.current.forEach((id) => window.clearTimeout(id))
      timersRef.current = []
    }, [])

    const reset = useCallback(() => {
      clearTimers()
      setVisibleCount(0)
      setActiveStep(1)
      setShowExtras(false)
      setPlaying(false)
    }, [clearTimers])

    const play = useCallback(() => {
      reset()
      setPlaying(true)
      setActiveStep(1)
      const t0 = window.setTimeout(() => setActiveStep(2), 400)
      timersRef.current.push(t0)

      script.forEach((line, index) => {
        const delay = 900 + index * 1400
        const tid = window.setTimeout(() => {
          setVisibleCount(index + 1)
          setActiveStep(line.step)
        }, delay)
        timersRef.current.push(tid)
      })

      const end = window.setTimeout(() => {
        setShowExtras(true)
        setActiveStep(5)
        setPlaying(false)
      }, 900 + script.length * 1400 + 600)
      timersRef.current.push(end)
    }, [reset])

    useImperativeHandle(ref, () => ({ play }), [play])

    useEffect(() => {
      if (playToken > 0) play()
    }, [playToken, play])

    useEffect(() => () => clearTimers(), [clearTimers])

    const visible = script.slice(0, visibleCount)

    return (
      <aside
        className="w-full max-w-xl rounded-2xl border border-karyuk-border bg-white p-4 shadow-[0_20px_50px_-24px_rgba(15,31,23,0.35)] sm:p-5"
        aria-label="Sample call illustration"
      >
        <div className="flex items-center justify-between gap-3 border-b border-karyuk-border pb-3">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${playing ? 'animate-pulse bg-karyuk-mint' : 'bg-karyuk-mint'}`}
              aria-hidden
            />
            <span className="text-sm font-medium text-karyuk-ink">
              Sample caller
            </span>
            <span className="rounded-md bg-karyuk-panel px-1.5 py-0.5 text-[10px] font-semibold tracking-wider text-karyuk-muted">
              SAMPLE
            </span>
          </div>
          <button
            type="button"
            onClick={() => (playing ? reset() : play())}
            className="inline-flex items-center gap-1.5 rounded-lg border border-karyuk-border bg-karyuk-panel px-2.5 py-1 text-xs font-medium text-karyuk-ink transition-colors hover:bg-white"
          >
            {playing ? (
              <>
                <Pause className="h-3.5 w-3.5" aria-hidden />
                Stop
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5" aria-hidden />
                {visibleCount === 0 ? 'Play illustration' : 'Replay'}
              </>
            )}
          </button>
        </div>

        <div className="mt-4 min-h-[220px] space-y-3">
          {visibleCount === 0 && !playing && (
            <p className="rounded-xl border border-dashed border-karyuk-border bg-karyuk-panel/60 px-4 py-6 text-center text-sm text-karyuk-muted">
              Press <span className="font-medium text-karyuk-ink">Play illustration</span> or{' '}
              <span className="font-medium text-karyuk-ink">View a sample call</span> to walk
              through a sample conversation.
            </p>
          )}
          {visible.map((line) => (
            <CallBubble
              key={`${line.time}-${line.message}`}
              role={line.role}
              time={line.time}
              message={line.message}
            />
          ))}

          {showExtras && (
            <>
              <div
                aria-live="polite"
                className="rounded-lg border border-karyuk-mint/30 bg-karyuk-mint-soft px-3 py-2 text-xs text-karyuk-green-dark"
              >
                <span className="font-semibold">Sample availability check</span>
                <span className="text-karyuk-muted"> · Not a live rate</span>
              </div>
              <p className="rounded-lg bg-karyuk-panel px-3 py-2 text-xs text-karyuk-muted">
                Sample ends before a confirmation · No booking created
              </p>
            </>
          )}
        </div>

        <div className="mt-5">
          <p className="text-xs font-medium text-karyuk-muted">
            Intended call path
          </p>
          <ol className="mt-3 grid grid-cols-5 gap-1 sm:gap-2">
            {callPath.map((item) => {
              const stepNum = Number(item.step)
              const active = activeStep === stepNum
              return (
                <li key={item.step} className="text-center">
                  <button
                    type="button"
                    onClick={() => setActiveStep(stepNum)}
                    className={`mx-auto flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold transition-colors ${
                      active
                        ? 'border-karyuk-mint bg-karyuk-mint-soft text-karyuk-green-dark'
                        : 'border-karyuk-border bg-white text-karyuk-green-dark hover:bg-karyuk-panel'
                    }`}
                    title={`${item.title}: ${item.subtitle}`}
                  >
                    {item.step}
                  </button>
                  <p className="mt-1.5 text-[11px] font-semibold leading-tight text-karyuk-ink">
                    {item.title}
                  </p>
                  <p className="mt-0.5 hidden text-[10px] leading-tight text-karyuk-muted sm:block">
                    {item.subtitle}
                  </p>
                </li>
              )
            })}
          </ol>
        </div>

        <p className="mt-4 border-t border-karyuk-border pt-3 text-center text-[10px] font-medium tracking-wide text-karyuk-muted">
          Sample call illustration · NOT A CUSTOMER RECORD
        </p>
      </aside>
    )
  },
)

function CallBubble({
  role,
  time,
  message,
}: {
  role: 'caller' | 'agent'
  time: string
  message: string
}) {
  const isAgent = role === 'agent'

  return (
    <div
      className={`flex gap-2.5 ${isAgent ? 'flex-row-reverse text-right' : ''}`}
    >
      <div
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-karyuk-border ${
          isAgent ? 'bg-karyuk-mint-soft text-karyuk-green-dark' : 'bg-karyuk-panel text-karyuk-muted'
        }`}
      >
        {isAgent ? (
          <Headphones className="h-3.5 w-3.5" aria-hidden />
        ) : (
          <User className="h-3.5 w-3.5" aria-hidden />
        )}
      </div>
      <div className={`min-w-0 flex-1 ${isAgent ? 'items-end' : ''}`}>
        <div className="flex items-baseline gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-karyuk-muted">
            {isAgent ? 'KARYUK' : 'Caller'}
          </span>
          <span className="text-[10px] tabular-nums text-karyuk-muted">{time}</span>
        </div>
        <p
          className={`mt-1 rounded-xl border px-3 py-2 text-sm leading-snug text-karyuk-ink ${
            isAgent
              ? 'border-karyuk-mint/25 bg-karyuk-mint-soft/60'
              : 'border-karyuk-border bg-karyuk-panel'
          }`}
        >
          {message}
        </p>
      </div>
    </div>
  )
}
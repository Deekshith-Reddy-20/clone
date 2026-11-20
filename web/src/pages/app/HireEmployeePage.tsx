import { Mic, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { TemplateGallery } from '../../components/TemplateGallery'
import {
  LANGUAGES,
  PENDING_TEMPLATE_STORAGE_KEY,
  getTemplateById,
  templateDefaults,
  type TemplateCard,
} from '../../data/employeeTemplates'
import { useAuth } from '../../context/AuthContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import { apiFetch, isApiEnabled } from '../../lib/api/client'
import type { CallMode } from '../../lib/workspace'

type EmployeeCreated = { id: string }

const MODES: { id: CallMode; title: string; subtitle: string }[] = [
  { id: 'instant', title: 'Instant', subtitle: 'Calls new leads in seconds' },
  { id: 'bulk', title: 'Bulk', subtitle: 'Works through a list' },
  { id: 'inbound', title: 'Inbound', subtitle: 'Answers incoming calls' },
]

export function HireEmployeePage() {
  const { user, authReady } = useAuth()
  const { createEmployeeFromBrief, state, completeOnboardingStep } = useWorkspace()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const briefRef = useRef<HTMLTextAreaElement>(null)

  const [brief, setBrief] = useState(
    'Call everyone who asks for a test drive and fix a slot',
  )
  const [language, setLanguage] = useState<string>(LANGUAGES[0])
  const [naturalSpoken, setNaturalSpoken] = useState(true)
  const [mode, setMode] = useState<CallMode>('instant')
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const firstName = user?.name.split(/\s+/)[0] ?? 'there'

  const applyTemplate = useCallback((t: TemplateCard) => {
    const d = templateDefaults(t)
    setBrief(d.brief)
    setLanguage(d.language)
    setMode(d.mode)
    setNaturalSpoken(d.naturalSpoken)
    setSelectedTemplateId(t.id)
    setError(null)
    window.sessionStorage.removeItem(PENDING_TEMPLATE_STORAGE_KEY)
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('template', t.id)
        return next
      },
      { replace: true },
    )
    briefRef.current?.focus()
    briefRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [setSearchParams])

  useEffect(() => {
    const id =
      searchParams.get('template') ||
      window.sessionStorage.getItem(PENDING_TEMPLATE_STORAGE_KEY)
    if (!id) return
    const t = getTemplateById(id)
    if (!t || selectedTemplateId === id) return
    const d = templateDefaults(t)
    setBrief(d.brief)
    setLanguage(d.language)
    setMode(d.mode)
    setNaturalSpoken(d.naturalSpoken)
    setSelectedTemplateId(t.id)
    window.sessionStorage.removeItem(PENDING_TEMPLATE_STORAGE_KEY)
    if (!searchParams.get('template')) {
      setSearchParams({ template: id }, { replace: true })
    }
  }, [searchParams, selectedTemplateId, setSearchParams])

  const scrollToTemplates = () => {
    document.getElementById('employee-templates')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
  }

  const onContinue = async () => {
    if (!authReady) return
    if (brief.trim().length < 12) {
      setError('Describe what your employee should do (at least a short sentence).')
      return
    }
    setError(null)

    if (isApiEnabled() && user?.workspaceId) {
      try {
        const created = await apiFetch<EmployeeCreated>(
          `/v1/workspaces/${user.workspaceId}/employees`,
          {
            method: 'POST',
            body: JSON.stringify({
              brief,
              language,
              natural_spoken: naturalSpoken,
              mode,
            }),
          },
        )
        completeOnboardingStep(1)
        navigate(`/app/team/${created.id}`)
        return
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not create employee')
        return
      }
    }

    try {
      const draft = createEmployeeFromBrief({
        brief,
        language,
        naturalSpoken,
        mode,
        templateId: selectedTemplateId ?? undefined,
      })
      completeOnboardingStep(1)
      navigate(`/app/team/${draft.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create employee')
    }
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="overflow-hidden rounded-[1.75rem] border border-karyuk-border bg-gradient-to-br from-[#2a2340] via-[#1f1a30] to-[#151020] p-6 text-white shadow-xl sm:p-8">
        <div className="flex items-center gap-2 text-sm text-white/70">
          <Sparkles className="h-4 w-4 text-violet-300" aria-hidden />
          Hire your first AI employee
        </div>

        <h1 className="mt-4 text-2xl font-semibold leading-snug sm:text-3xl">
          What should your first AI employee do, {firstName}?
        </h1>

        <textarea
          ref={briefRef}
          value={brief}
          onChange={(e) => {
            setBrief(e.target.value)
            setSelectedTemplateId(null)
          }}
          rows={3}
          className="mt-6 w-full resize-none rounded-2xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white placeholder:text-white/40 outline-none ring-violet-400/50 focus:ring-2"
          placeholder="Call everyone who asks for a test drive and fix a slot"
        />

        {selectedTemplateId && (
          <p className="mt-2 text-xs text-violet-200">
            Template: {getTemplateById(selectedTemplateId)?.title} — edit the brief above if needed.
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label className="text-xs font-medium text-white/60" htmlFor="lang">
            Language
          </label>
          <select
            id="lang"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="rounded-xl border border-white/15 bg-black/30 px-3 py-2 text-sm text-white outline-none"
          >
            {LANGUAGES.map((lang) => (
              <option key={lang} value={lang} className="text-karyuk-ink">
                {lang}
              </option>
            ))}
          </select>

          <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-white/80">
            <input
              type="checkbox"
              checked={naturalSpoken}
              onChange={(e) => setNaturalSpoken(e.target.checked)}
              className="rounded border-white/30"
            />
            Natural spoken
          </label>
        </div>

        {error && (
          <p className="mt-3 text-sm text-red-300" role="alert">
            {error}
          </p>
        )}

        <div className="mt-6 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={scrollToTemplates}
            className="rounded-full border border-white/20 px-4 py-2 text-sm font-medium text-white/90 hover:bg-white/10"
          >
            Pick a template
          </button>
          <button
            type="button"
            onClick={onContinue}
            disabled={!authReady}
            className="inline-flex items-center gap-2 rounded-full bg-violet-500 px-5 py-2 text-sm font-semibold text-white hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Mic className="h-4 w-4" aria-hidden />
            Continue
          </button>
        </div>

        <div className="mt-6 flex flex-wrap gap-2 border-t border-white/10 pt-5">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              className={`min-w-[7rem] flex-1 rounded-2xl border px-3 py-3 text-left transition-colors sm:max-w-[10rem] ${
                mode === m.id
                  ? 'border-violet-400/60 bg-violet-500/20'
                  : 'border-white/10 bg-black/20 hover:bg-white/5'
              }`}
            >
              <p className="text-sm font-semibold">{m.title}</p>
              <p className="mt-0.5 text-[11px] text-white/55">{m.subtitle}</p>
            </button>
          ))}
        </div>
      </div>

      <section className="mt-10 scroll-mt-24">
        <h2 className="text-lg font-semibold text-karyuk-ink">Templates</h2>
        <p className="mt-1 text-sm text-karyuk-muted">
          Start from an industry playbook — fills the brief, language, and call mode.
        </p>
        <TemplateGallery
          selectedId={selectedTemplateId}
          onSelect={applyTemplate}
        />
      </section>

      {state.employees.length > 0 && (
        <p className="mt-8 text-sm text-karyuk-muted">
          <Link to="/app/team" className="font-medium text-karyuk-green-dark hover:underline">
            View your team ({state.employees.length})
          </Link>
        </p>
      )}
    </div>
  )
}
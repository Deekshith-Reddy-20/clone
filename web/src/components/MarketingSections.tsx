import { Calendar, Headphones, LineChart, Shield, Zap } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { EMPLOYEE_TEMPLATES, INDUSTRY_TEMPLATE_MAP } from '../data/employeeTemplates'
import { useAuth } from '../context/AuthContext'
import { goToHireWithTemplate } from '../lib/templateNavigation'

export function MarketingSections() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const pickTemplate = (templateId: string) => {
    goToHireWithTemplate(templateId, navigate, Boolean(user))
  }

  return (
    <div className="space-y-24 border-t border-karyuk-border/80 pb-24 pt-20">
      <section id="product" className="scroll-mt-24">
        <h2 className="text-2xl font-semibold tracking-tight text-karyuk-ink sm:text-3xl">
          Product
        </h2>
        <p className="mt-3 max-w-2xl text-karyuk-muted">
          KARYUK is an AI front-desk employee that answers calls, follows your
          playbook, checks connected systems, and escalates to humans when needed.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          {[
            {
              icon: Headphones,
              title: 'Always on',
              text: 'Inbound and outbound calling with consistent tone and scripts.',
            },
            {
              icon: Calendar,
              title: 'Action-ready',
              text: 'Calendar, sheets, and webhooks when your workspace connects them.',
            },
            {
              icon: Shield,
              title: 'Tenant-safe',
              text: 'Workspaces, roles, and recordings scoped per customer.',
            },
          ].map((card) => (
            <article
              key={card.title}
              className="rounded-2xl border border-karyuk-border bg-white p-5 shadow-sm"
            >
              <card.icon className="h-5 w-5 text-karyuk-mint" aria-hidden />
              <h3 className="mt-3 font-semibold text-karyuk-ink">{card.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-karyuk-muted">
                {card.text}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section id="how-it-works" className="scroll-mt-24">
        <h2 className="text-2xl font-semibold tracking-tight text-karyuk-ink sm:text-3xl">
          How it works
        </h2>
        <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { step: '1', label: 'Create workspace', body: 'Invite your team and set timezone.' },
            { step: '2', label: 'Hire an employee', body: 'Brief from text or voice, then publish.' },
            { step: '3', label: 'Connect a number', body: 'Assign routing for inbound and outbound.' },
            { step: '4', label: 'Review results', body: 'Transcripts, outcomes, and credit usage.' },
          ].map((item) => (
            <li
              key={item.step}
              className="rounded-2xl border border-karyuk-border bg-karyuk-panel/50 p-5"
            >
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-karyuk-green-dark text-sm font-semibold text-white">
                {item.step}
              </span>
              <p className="mt-3 font-semibold text-karyuk-ink">{item.label}</p>
              <p className="mt-1 text-sm text-karyuk-muted">{item.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="templates" className="scroll-mt-24">
        <h2 className="text-2xl font-semibold tracking-tight text-karyuk-ink sm:text-3xl">
          Templates
        </h2>
        <p className="mt-3 max-w-2xl text-karyuk-muted">
          One-click playbooks — opens hire with brief, language, and call mode pre-filled.
        </p>
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {EMPLOYEE_TEMPLATES.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => pickTemplate(t.id)}
                className="flex h-full w-full flex-col rounded-2xl border border-karyuk-border bg-white p-4 text-left shadow-sm transition hover:border-karyuk-mint/50 hover:shadow-md"
              >
                <span className="text-[10px] font-bold uppercase tracking-wider text-karyuk-muted">
                  {t.industry}
                </span>
                <span className="mt-2 font-semibold text-karyuk-ink">{t.title}</span>
                <span className="mt-2 line-clamp-2 text-xs text-karyuk-muted">{t.brief}</span>
                <span className="mt-3 text-xs font-medium text-karyuk-green-dark">Use template →</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section id="industries" className="scroll-mt-24">
        <h2 className="text-2xl font-semibold tracking-tight text-karyuk-ink sm:text-3xl">
          Industries
        </h2>
        <ul className="mt-8 grid gap-4 sm:grid-cols-2">
          {INDUSTRY_TEMPLATE_MAP.map((item) => (
            <li key={item.title}>
              <button
                type="button"
                onClick={() => pickTemplate(item.templateId)}
                className="w-full rounded-2xl border border-karyuk-border bg-white px-5 py-4 text-left transition hover:border-karyuk-mint/50 hover:bg-karyuk-panel/30"
              >
                <p className="font-semibold text-karyuk-ink">{item.title}</p>
                <p className="mt-1 text-sm text-karyuk-muted">{item.detail}</p>
                <p className="mt-2 text-xs font-medium text-karyuk-green-dark">Start with template →</p>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section id="platform" className="scroll-mt-24">
        <h2 className="text-2xl font-semibold tracking-tight text-karyuk-ink sm:text-3xl">
          Platform
        </h2>
        <p className="mt-3 max-w-2xl text-karyuk-muted">
          FastAPI backend, Keycloak identity, PostgreSQL records, workers for
          campaigns, and a dedicated voice runtime—designed for real telephony and
          billing, not demo mocks.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <PlatformPill icon={Zap} label="Instant leads API" />
          <PlatformPill icon={LineChart} label="Analytics & exports" />
          <PlatformPill icon={Shield} label="Webhook signing & audit" />
        </div>
      </section>
    </div>
  )
}

function PlatformPill({
  icon: Icon,
  label,
}: {
  icon: typeof Zap
  label: string
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-karyuk-border bg-white px-4 py-2 text-sm text-karyuk-muted">
      <Icon className="h-4 w-4 text-karyuk-mint" aria-hidden />
      {label}
    </span>
  )
}
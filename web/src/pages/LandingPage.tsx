import { Phone, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { LandingHeader } from '../components/LandingHeader'
import { MarketingSections } from '../components/MarketingSections'
import { SampleCallPanel } from '../components/SampleCallPanel'
import { scrollToSection } from '../lib/scroll'

export function LandingPage() {
  const location = useLocation()
  const [playToken, setPlayToken] = useState(0)

  useEffect(() => {
    const scrollTo = (location.state as { scrollTo?: string } | null)?.scrollTo
    if (!scrollTo) return
    const timer = window.setTimeout(() => scrollToSection(scrollTo), 50)
    return () => window.clearTimeout(timer)
  }, [location.state])

  const viewSampleCall = () => {
    scrollToSection('sample-call')
    setPlayToken((n) => n + 1)
  }

  return (
    <div className="bg-grid min-h-svh">
      <LandingHeader />

      <main className="mx-auto max-w-6xl px-6 py-12 lg:px-8 lg:py-16">
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <section className="max-w-xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-karyuk-border bg-white/90 px-3 py-1 text-[11px] font-semibold tracking-[0.12em] text-karyuk-green-dark shadow-sm">
              <span
                className="h-1.5 w-1.5 rounded-full bg-karyuk-mint"
                aria-hidden
              />
              YOUR AI FRONT DESK EMPLOYEE
            </div>

            <h1 className="mt-6 text-4xl font-semibold leading-[1.08] tracking-tight text-karyuk-ink sm:text-5xl lg:text-[3.25rem]">
              Every call answered.
              <br />
              Every booking handled.
            </h1>

            <p className="mt-5 text-base leading-relaxed text-karyuk-muted sm:text-lg">
              KARYUK answers calls, checks connected systems when a booking or
              availability request needs it, and involves your team only when it
              needs a person.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={viewSampleCall}
                className="inline-flex items-center justify-center gap-2 rounded-full border border-karyuk-border bg-white px-6 py-3 text-sm font-medium text-karyuk-ink shadow-sm transition-colors hover:bg-karyuk-panel"
              >
                <Phone className="h-4 w-4 text-karyuk-muted" aria-hidden />
                View a sample call
              </button>
            </div>

            <p className="mt-8 flex items-start gap-2 text-sm text-karyuk-muted">
              <ShieldCheck
                className="mt-0.5 h-4 w-4 shrink-0 text-karyuk-mint"
                aria-hidden
              />
              <span>
                Built for resorts, hotels, clinics, and consultation businesses.
              </span>
            </p>
          </section>

          <div id="sample-call" className="scroll-mt-24 flex justify-center lg:justify-end">
            <SampleCallPanel playToken={playToken} />
          </div>
        </div>

        <MarketingSections />
      </main>
    </div>
  )
}
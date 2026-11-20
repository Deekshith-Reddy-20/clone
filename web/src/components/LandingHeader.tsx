import { Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { scrollToSection } from '../lib/scroll'

const navLinks = [
  { label: 'Product', sectionId: 'product' },
  { label: 'Templates', sectionId: 'templates' },
  { label: 'How It Works', sectionId: 'how-it-works' },
  { label: 'Industries', sectionId: 'industries' },
  { label: 'Platform', sectionId: 'platform' },
]

export function LandingHeader() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useAuth()
  const [open, setOpen] = useState(false)

  const goToSection = (sectionId: string) => {
    setOpen(false)
    if (location.pathname !== '/') {
      navigate('/', { state: { scrollTo: sectionId } })
      return
    }
    scrollToSection(sectionId)
  }

  return (
    <header className="sticky top-0 z-50 border-b border-karyuk-border/80 bg-white/90 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6 lg:px-8">
        <Link to="/" className="flex items-center gap-2.5" onClick={() => setOpen(false)}>
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-karyuk-green-dark text-sm font-semibold tracking-tight text-white">
            K
          </span>
          <span className="text-lg font-semibold tracking-wide text-karyuk-ink">
            KARYUK
          </span>
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {navLinks.map((link) => (
            <button
              key={link.label}
              type="button"
              onClick={() => goToSection(link.sectionId)}
              className="text-sm font-medium text-karyuk-muted transition-colors hover:text-karyuk-ink"
            >
              {link.label}
            </button>
          ))}
        </nav>

        {user ? (
          <div className="hidden items-center gap-3 sm:flex">
            <Link
              to="/app"
              className="rounded-full bg-karyuk-green-dark px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-karyuk-green"
            >
              Open workspace
            </Link>
          </div>
        ) : (
          <div className="hidden w-0 sm:block sm:w-0" aria-hidden />
        )}

        <button
          type="button"
          className="inline-flex items-center justify-center rounded-lg border border-karyuk-border p-2 text-karyuk-ink md:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? 'Close menu' : 'Open menu'}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {open && (
        <div className="border-t border-karyuk-border bg-white px-6 py-4 md:hidden">
          <nav className="flex flex-col gap-3">
            {navLinks.map((link) => (
              <button
                key={link.label}
                type="button"
                onClick={() => goToSection(link.sectionId)}
                className="text-left text-sm font-medium text-karyuk-ink"
              >
                {link.label}
              </button>
            ))}
            {user ? (
              <div className="mt-2 flex flex-col gap-2 border-t border-karyuk-border pt-3">
                <Link
                  to="/app"
                  className="rounded-full bg-karyuk-green-dark px-4 py-2 text-center text-sm font-medium text-white"
                  onClick={() => setOpen(false)}
                >
                  Open workspace
                </Link>
              </div>
            ) : null}
          </nav>
        </div>
      )}
    </header>
  )
}
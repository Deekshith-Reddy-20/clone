import {
  BarChart3,
  CreditCard,
  Hash,
  LayoutGrid,
  MessageSquare,
  PhoneCall,
  PhoneIncoming,
  Settings,
  Sparkles,
  Users,
  Volume2,
  Zap,
} from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { useWorkspace } from '../../context/WorkspaceContext'
import { CreditsWidget } from './CreditsWidget'

type NavItem = {
  to: string
  label: string
  icon: typeof Sparkles
  end?: boolean
}

const sections: { title: string; items: NavItem[] }[] = [
  {
    title: 'AI Employees',
    items: [
      { to: '/app/team', label: 'Your team', icon: Users },
      { to: '/app', label: 'Hire & templates', icon: Sparkles, end: true },
    ],
  },
  {
    title: 'Results',
    items: [
      { to: '/app/leads', label: 'Leads', icon: LayoutGrid },
      { to: '/app/conversations', label: 'Conversations', icon: MessageSquare },
      { to: '/app/performance', label: 'Performance', icon: BarChart3 },
    ],
  },
  {
    title: 'Calling',
    items: [
      { to: '/app/campaigns', label: 'Campaigns', icon: PhoneCall },
      { to: '/app/instant', label: 'Instant leads', icon: Zap },
      { to: '/app/voice-agents', label: 'Voice agents', icon: Volume2 },
      { to: '/app/incoming', label: 'Incoming calls', icon: PhoneIncoming },
    ],
  },
  {
    title: 'Workspace',
    items: [
      { to: '/app/numbers', label: 'Numbers & channels', icon: Hash },
      { to: '/app/billing', label: 'Credits & billing', icon: CreditCard },
      { to: '/app/settings', label: 'Settings', icon: Settings },
      { to: '/app/developers', label: 'Developers', icon: LayoutGrid },
    ],
  },
]

function linkClass({ isActive }: { isActive: boolean }) {
  return [
    'flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition-colors',
    isActive
      ? 'bg-karyuk-mint-soft text-karyuk-green-dark'
      : 'text-karyuk-muted hover:bg-white hover:text-karyuk-ink',
  ].join(' ')
}

export function AppSidebar() {
  const { state } = useWorkspace()

  return (
    <aside className="flex w-[248px] shrink-0 flex-col border-r border-karyuk-border bg-white">
      <div className="border-b border-karyuk-border px-4 py-4">
        <p className="truncate text-sm font-semibold text-karyuk-ink">Karyuk</p>
        <p className="truncate text-xs text-karyuk-muted">Workspace</p>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-wider text-karyuk-muted">
              {section.title}
            </p>
            <ul className="space-y-0.5">
              {section.items.map((item) => (
                <li key={item.to + item.label}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={linkClass}
                  >
                    <item.icon className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
                    {item.label}
                    {item.to === '/app/team' && state.employees.length > 0 && (
                      <span className="ml-auto rounded-md bg-karyuk-panel px-1.5 text-[10px] font-semibold text-karyuk-muted">
                        {state.employees.length}
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-karyuk-border p-3 space-y-2">
        <CreditsWidget compact />
        <Link
          to="/"
          className="block w-full rounded-xl border border-karyuk-border py-2 text-center text-xs font-medium text-karyuk-muted hover:bg-karyuk-panel hover:text-karyuk-ink"
        >
          Home
        </Link>
      </div>
    </aside>
  )
}
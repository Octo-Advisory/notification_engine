import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import {
  BookOpen, ExternalLink, LayoutDashboard, Mail, Menu, MessagesSquare, Send, Settings, Users, Workflow, X,
} from 'lucide-react'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/messages', label: 'Message Log', icon: Mail },
  { to: '/rules', label: 'Rules', icon: Workflow },
  { to: '/destinations', label: 'Destinations', icon: Send },
  { to: '/users', label: 'Teams Users', icon: Users },
  { to: '/install', label: 'Install Guide', icon: BookOpen },
]

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="w-8 h-8 rounded-lg bg-accent text-white grid place-items-center">
        <MessagesSquare size={18} />
      </div>
      <div className="leading-tight">
        <div className="font-semibold">Teams Notify</div>
        <div className="text-[11px] text-ink-3">Microsoft Teams for Frappe</div>
      </div>
    </div>
  )
}

function Nav({ onNavigate }) {
  return (
    <nav className="flex flex-col gap-0.5 mt-6">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-2.5 px-3 h-9 rounded-md font-medium no-underline ${
              isActive ? 'bg-accent-soft text-accent-text' : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
            }`
          }
        >
          <Icon size={17} /> {label}
        </NavLink>
      ))}
      <div className="border-t border-line my-3" />
      <a href="/app/teams-settings" className="flex items-center gap-2.5 px-3 h-9 rounded-md text-ink-2 hover:bg-surface-2 hover:text-ink no-underline">
        <Settings size={17} /> Settings <ExternalLink size={12} className="ml-auto text-ink-3" />
      </a>
      <a href="/app" className="flex items-center gap-2.5 px-3 h-9 rounded-md text-ink-2 hover:bg-surface-2 hover:text-ink no-underline">
        <ExternalLink size={17} /> Back to Desk
      </a>
    </nav>
  )
}

export default function Layout() {
  const [open, setOpen] = useState(false)
  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden md:block w-60 flex-none border-r border-line bg-surface px-3 py-4 sticky top-0 h-screen">
        <Logo />
        <Nav />
      </aside>

      {/* Mobile top bar + drawer */}
      <div className="md:hidden flex items-center justify-between border-b border-line bg-surface px-4 h-14 sticky top-0 z-30">
        <Logo />
        <button className="btn btn-ghost" aria-label="Open menu" onClick={() => setOpen(true)}><Menu size={18} /></button>
      </div>
      {open && (
        <div className="md:hidden fixed inset-0 z-40 bg-black/40" onClick={() => setOpen(false)}>
          <aside className="w-64 h-full bg-surface px-3 py-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <Logo />
              <button className="btn btn-ghost" aria-label="Close menu" onClick={() => setOpen(false)}><X size={18} /></button>
            </div>
            <Nav onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <main className="flex-1 min-w-0 px-4 md:px-8 py-6 max-w-[1200px]">
        <Outlet />
      </main>
    </div>
  )
}

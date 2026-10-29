import { NavLink, Outlet } from 'react-router-dom'
import { Boxes, LayoutDashboard, LogOut, Moon, Sun } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useTheme } from '@/hooks/useTheme'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/items', label: 'Items', icon: Boxes, end: false },
]

export default function Layout() {
  const { user, config, logout } = useAuth()
  const { theme, toggle } = useTheme()

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-base bg-surface p-4 sm:block">
        <div className="mb-8 px-2">
          <p className="text-sm font-semibold">{config?.app_name ?? 'Boilerplate'}</p>
          <p className="text-xs text-muted">v{config?.version ?? '0.1.0'}</p>
        </div>
        <nav className="space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                  isActive ? 'bg-primary text-primary-fg' : 'text-muted hover:bg-bg'
                }`
              }
            >
              <Icon size={17} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-base bg-surface px-5 py-3">
          <div className="text-sm text-muted">
            {user?.display_name ?? user?.username}
            {user?.role && (
              <span className="ml-2 rounded-full border border-base px-2 py-0.5 text-xs">
                {user.role}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={toggle}
              aria-label="Toggle theme"
              className="rounded-lg p-2 text-muted hover:bg-bg"
            >
              {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            {config?.provider !== 'none' && (
              <button
                onClick={() => void logout()}
                aria-label="Sign out"
                className="rounded-lg p-2 text-muted hover:bg-bg"
              >
                <LogOut size={17} />
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

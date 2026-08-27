import { FileText, MessageSquare, Settings, Wrench } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { ThemeToggle } from './theme-toggle';

const NAV_ITEMS = [
  { to: '/', label: 'Chat', icon: MessageSquare, end: true },
  { to: '/documents', label: 'Documents', icon: FileText, end: false },
  { to: '/system', label: 'System', icon: Settings, end: true },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main navigation" className="flex flex-col gap-1">
      {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              'hover:bg-accent hover:text-accent-foreground',
              isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground',
            )
          }
        >
          <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

/**
 * Application chrome: a persistent sidebar on desktop, a slide-over drawer on
 * mobile (opened from the header). Content routes render in `children`.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex h-full flex-col md:flex-row">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r bg-card md:flex md:flex-col">
        <div className="flex items-center gap-2 border-b px-4 py-4">
          <Wrench className="h-5 w-5 text-primary" aria-hidden="true" />
          <span className="text-sm font-semibold">Engineering Docs</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <NavList />
        </div>
      </aside>

      {/* Mobile header + drawer */}
      <header className="flex items-center justify-between border-b bg-card px-4 py-3 md:hidden">
        <div className="flex items-center gap-2">
          <Wrench className="h-5 w-5 text-primary" aria-hidden="true" />
          <span className="text-sm font-semibold">Engineering Docs</span>
        </div>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <Button
            variant="ghost"
            size="icon"
            aria-label={mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={mobileNavOpen}
            aria-controls="mobile-nav-drawer"
            onClick={() => setMobileNavOpen((open) => !open)}
          >
            <MenuIcon open={mobileNavOpen} />
          </Button>
        </div>
      </header>
      {mobileNavOpen && (
        <div
          id="mobile-nav-drawer"
          className="border-b bg-card px-3 py-3 md:hidden"
          role="dialog"
          aria-label="Navigation"
        >
          <NavList onNavigate={() => setMobileNavOpen(false)} />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="hidden items-center justify-end border-b bg-card px-4 py-2 md:flex">
          <ThemeToggle />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

function MenuIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      aria-hidden="true"
    >
      {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 6h16M4 12h16M4 18h16" />}
    </svg>
  );
}

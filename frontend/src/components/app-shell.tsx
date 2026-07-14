import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { BookOpen, ChefHat, CookingPot, LogOut, Refrigerator, UserRound } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { cn } from '../lib/utils'
import { Button } from './ui'

const nav = [
  { to: '/', label: 'Recipes', icon: CookingPot },
  { to: '/fridge', label: 'Fridge', icon: Refrigerator },
  { to: '/library', label: 'Library', icon: BookOpen },
] as const

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-3" aria-label="Recipe Finder home">
      <span className="grid size-10 place-items-center rounded-2xl bg-terracotta text-white shadow-sm">
        <ChefHat className="size-6" />
      </span>
      <span>
        <span className="block font-display text-xl font-bold leading-none text-ink">Recipe Finder</span>
        <span className="mt-1 block text-[10px] font-bold uppercase tracking-[.18em] text-muted">
          Cook with what you have
        </span>
      </span>
    </Link>
  )
}

export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  return (
    <div className="min-h-dvh bg-cream">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-line bg-white/90 p-5 backdrop-blur-xl lg:flex">
        <Brand />
        <nav className="mt-10 grid gap-2" aria-label="Primary navigation">
          {nav.map(({ to, label, icon: Icon }) => {
            const active = to === '/' ? pathname === '/' : pathname.startsWith(to)
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  'flex items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-semibold transition',
                  active ? 'bg-sage text-white shadow-sm' : 'text-muted hover:bg-sand hover:text-ink',
                )}
              >
                <Icon className="size-5" />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="mt-auto rounded-2xl bg-sand p-4">
          <Link to="/account" className="flex items-center gap-3 rounded-xl">
            <span className="grid size-9 place-items-center rounded-full bg-white text-sage-dark">
              <UserRound className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-bold text-ink">
                {user?.name || 'Home cook'}
              </span>
              <span className="block truncate text-xs text-muted">{user?.email}</span>
            </span>
          </Link>
          <Button
            className="mt-3 w-full"
            variant="ghost"
            size="sm"
            onClick={async () => {
              await logout()
              await navigate({ to: '/login' })
            }}
          >
            <LogOut className="size-4" /> Log out
          </Button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex h-18 items-center justify-between border-b border-line bg-cream/90 px-4 backdrop-blur-xl lg:hidden">
        <Brand />
        <Link
          to="/account"
          aria-label="Account"
          className="grid size-10 place-items-center rounded-full border border-line bg-white text-ink"
        >
          <UserRound className="size-5" />
        </Link>
      </header>

      <main className="min-h-dvh pb-24 lg:ml-64 lg:pb-0">
        <Outlet />
      </main>

      <nav
        className="fixed inset-x-3 bottom-3 z-30 grid grid-cols-3 rounded-2xl border border-line bg-white/95 p-1.5 shadow-xl backdrop-blur lg:hidden"
        aria-label="Mobile navigation"
      >
        {nav.map(({ to, label, icon: Icon }) => {
          const active = to === '/' ? pathname === '/' : pathname.startsWith(to)
          return (
            <Link
              key={to}
              to={to}
              className={cn(
                'flex flex-col items-center gap-1 rounded-xl py-2 text-[11px] font-bold',
                active ? 'bg-sage text-white' : 'text-muted',
              )}
            >
              <Icon className="size-5" />
              {label}
            </Link>
          )
        })}
      </nav>
    </div>
  )
}

export function RecipeArt({ seed = 'herbs', className }: { seed?: string; className?: string }) {
  const tone = [...seed].reduce((sum, letter) => sum + letter.charCodeAt(0), 0) % 4
  const backgrounds = [
    'from-orange-100 via-amber-50 to-emerald-100',
    'from-rose-100 via-orange-50 to-lime-100',
    'from-lime-100 via-stone-50 to-yellow-100',
    'from-amber-100 via-rose-50 to-sky-100',
  ]
  return (
    <div
      className={cn(
        'relative isolate overflow-hidden bg-gradient-to-br',
        backgrounds[tone],
        className,
      )}
      aria-hidden="true"
    >
      <span className="absolute -right-8 -top-9 size-28 rounded-full border-[18px] border-white/45" />
      <span className="absolute bottom-3 left-5 size-16 rotate-12 rounded-[45%_55%_60%_40%] bg-sage/20" />
      <span className="absolute bottom-7 right-12 size-10 rounded-full bg-terracotta/20 shadow-[18px_-15px_0_4px_rgba(182,91,61,.12)]" />
      <ChefHat className="absolute left-1/2 top-1/2 size-12 -translate-x-1/2 -translate-y-1/2 text-ink/15" />
    </div>
  )
}

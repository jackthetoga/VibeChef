import { useState } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { ArrowRight, ChefHat, KeyRound, LogOut, Mail, ShieldCheck, Sparkles, UserRound } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { Button, Card, Field, Input } from '../components/ui'

function safeRedirect(value: unknown) {
  if (typeof value !== 'string') return '/'
  try {
    const target = new URL(value, window.location.origin)
    if (target.origin !== window.location.origin) return '/'
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return '/'
  }
}

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as { redirect?: string }
  const auth = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const register = mode === 'register'

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (register) await auth.register(name, email, password)
      else await auth.login(email, password)
      await navigate({ to: safeRedirect(search.redirect) as never })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-dvh bg-cream lg:grid-cols-[1.1fr_.9fr]">
      <section className="relative hidden overflow-hidden bg-sage-dark p-12 text-white lg:flex lg:flex-col">
        <div className="absolute inset-0 opacity-20 kitchen-pattern" />
        <div className="relative flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-2xl bg-terracotta"><ChefHat className="size-6" /></span>
          <span className="font-display text-2xl font-bold">Recipe Finder</span>
        </div>
        <div className="relative my-auto max-w-xl">
          <span className="mb-6 grid size-14 place-items-center rounded-2xl bg-white/10"><Sparkles className="size-7 text-amber-200" /></span>
          <h1 className="font-display text-6xl font-bold leading-[1.05] tracking-tight">Your cookbooks.<br />Your fridge.<br /><span className="text-amber-200">Dinner solved.</span></h1>
          <p className="mt-7 max-w-lg text-lg leading-relaxed text-white/70">Find the right recipe for the ingredients you already have—without scrolling for hours.</p>
        </div>
        <p className="relative text-sm text-white/50">Less waste. More delicious dinners.</p>
      </section>

      <section className="flex items-center justify-center p-5 sm:p-10">
        <div className="w-full max-w-md">
          <div className="mb-9 flex items-center gap-3 lg:hidden">
            <span className="grid size-10 place-items-center rounded-xl bg-terracotta text-white"><ChefHat className="size-6" /></span>
            <span className="font-display text-xl font-bold text-ink">Recipe Finder</span>
          </div>
          <p className="mb-2 text-xs font-bold uppercase tracking-[.18em] text-terracotta">{register ? 'Join the kitchen' : 'Welcome back'}</p>
          <h1 className="font-display text-4xl font-bold tracking-tight text-ink">{register ? 'Create your account' : 'Ready to cook?'}</h1>
          <p className="mt-2 text-muted">{register ? 'Start turning what you have into meals you love.' : 'Sign in to see what’s on the menu.'}</p>

          <form className="mt-8 grid gap-5" onSubmit={submit}>
            {register && <Field label="Name"><div className="relative"><UserRound className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" /><Input className="pl-10" autoComplete="name" required value={name} onChange={(event) => setName(event.target.value)} placeholder="Alex Cook" /></div></Field>}
            <Field label="Email"><div className="relative"><Mail className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" /><Input className="pl-10" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></div></Field>
            <Field label="Password" hint={register ? 'Use at least 8 characters.' : undefined}><div className="relative"><KeyRound className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" /><Input className="pl-10" type="password" minLength={8} autoComplete={register ? 'new-password' : 'current-password'} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="••••••••" /></div></Field>
            {error && <p role="alert" className="rounded-xl bg-rose-100 p-3 text-sm font-semibold text-rose-800">{error}</p>}
            <Button className="mt-1 w-full" size="lg" type="submit" disabled={submitting}>
              {submitting ? 'One moment…' : register ? 'Create account' : 'Sign in'} <ArrowRight className="size-4" />
            </Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted">
            {register ? 'Already have an account?' : 'New to Recipe Finder?'}{' '}
            <Link to={register ? '/login' : '/register'} className="font-bold text-sage-dark hover:underline">{register ? 'Sign in' : 'Create an account'}</Link>
          </p>
          <p className="mt-8 flex items-center justify-center gap-2 text-xs text-muted"><ShieldCheck className="size-4" /> Your recipes and pantry stay private.</p>
        </div>
      </section>
    </main>
  )
}

export function AccountPage() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="mx-auto max-w-3xl p-4 sm:p-8 xl:p-10">
      <p className="mb-2 text-xs font-bold uppercase tracking-[.18em] text-terracotta">Settings</p>
      <h1 className="font-display text-4xl font-bold text-ink">Your account</h1>
      <Card className="mt-8 p-6 sm:p-8">
        <div className="flex items-center gap-4">
          <span className="grid size-16 place-items-center rounded-full bg-sand text-sage-dark"><UserRound className="size-7" /></span>
          <div><h2 className="font-display text-2xl font-bold text-ink">{user?.name || 'Home cook'}</h2><p className="text-muted">{user?.email}</p></div>
        </div>
        <div className="mt-7 border-t border-line pt-6">
          <Button variant="danger" onClick={async () => { await logout(); await navigate({ to: '/login' }) }}><LogOut className="size-4" /> Log out</Button>
        </div>
      </Card>
    </div>
  )
}

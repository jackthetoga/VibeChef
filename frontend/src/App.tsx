import { useEffect } from 'react'
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router'
import { ChefHat } from 'lucide-react'
import { AppShell } from './components/app-shell'
import { useAuth } from './lib/auth'
import { AccountPage, AuthPage } from './pages/auth'
import { FridgePage } from './pages/fridge'
import { LibraryPage } from './pages/library'
import { RecipeDetailPage } from './pages/recipe-detail'
import { RecipesPage } from './pages/recipes'

type AuthState = ReturnType<typeof useAuth>
interface RouterContext {
  auth: AuthState
}

interface AuthSearch {
  redirect?: string
}

function validateAuthSearch(search: Record<string, unknown>): AuthSearch {
  return {
    redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
  }
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  notFoundComponent: () => (
    <main className="grid min-h-dvh place-items-center bg-cream p-6 text-center">
      <div>
        <p className="font-display text-7xl font-bold text-terracotta">404</p>
        <h1 className="mt-2 font-display text-2xl font-bold text-ink">That recipe wandered off</h1>
        <Link to="/" className="mt-4 inline-block font-bold text-sage-dark hover:underline">Back to the kitchen</Link>
      </div>
    </main>
  ),
})

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: validateAuthSearch,
  beforeLoad: ({ context }) => {
    if (context.auth.user) throw redirect({ to: '/' })
  },
  component: () => <AuthPage mode="login" />,
})
const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/register',
  beforeLoad: ({ context }) => {
    if (context.auth.user) throw redirect({ to: '/' })
  },
  component: () => <AuthPage mode="register" />,
})
const protectedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: '_authenticated',
  beforeLoad: ({ context, location }) => {
    if (!context.auth.user) {
      throw redirect({ to: '/login', search: { redirect: location.href } as never })
    }
  },
  component: AppShell,
})
const recipesRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/',
  component: RecipesPage,
})
const recipeDetailRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/recipes/$recipeId',
  component: RecipeDetailPage,
})
const fridgeRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/fridge',
  component: FridgePage,
})
const libraryRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/library',
  component: LibraryPage,
})
const accountRoute = createRoute({
  getParentRoute: () => protectedRoute,
  path: '/account',
  component: AccountPage,
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  registerRoute,
  protectedRoute.addChildren([
    recipesRoute,
    recipeDetailRoute,
    fridgeRoute,
    libraryRoute,
    accountRoute,
  ]),
])

const router = createRouter({ routeTree, context: { auth: undefined! } })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

export default function App() {
  const auth = useAuth()
  useEffect(() => {
    if (!auth.loading) void router.invalidate()
  }, [auth.loading, auth.user])

  if (auth.loading) {
    return (
      <main className="grid min-h-dvh place-items-center bg-cream">
        <div className="text-center">
          <span className="mx-auto grid size-14 animate-pulse place-items-center rounded-2xl bg-terracotta text-white"><ChefHat className="size-7" /></span>
          <p className="mt-4 font-display text-lg font-bold text-ink">Warming up the kitchen…</p>
        </div>
      </main>
    )
  }
  return <RouterProvider router={router} context={{ auth }} />
}

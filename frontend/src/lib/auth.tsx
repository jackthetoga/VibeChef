/* oxlint-disable react/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { authApi, onSessionCleared } from './api/client'
import type { User } from './api/types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const queryClient = useQueryClient()

  useEffect(() => {
    let active = true
    authApi
      .restore()
      .then((restored) => active && setUser(restored))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [])

  useEffect(
    () =>
      onSessionCleared(() => {
        setUser(null)
        queryClient.clear()
      }),
    [queryClient],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      async login(email, password) {
        const response = await authApi.login({ email, password })
        setUser(response.user || (await authApi.me()))
      },
      async register(name, email, password) {
        const response = await authApi.register({ name, email, password })
        setUser(response.user || (await authApi.me()))
      },
      async logout() {
        await authApi.logout()
        setUser(null)
        queryClient.clear()
      },
    }),
    [loading, queryClient, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}

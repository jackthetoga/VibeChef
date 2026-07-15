import type {
  AuthResponse,
  AuthTokens,
  Cookbook,
  CommonIngredient,
  CursorPage,
  Ingredient,
  PantryBulkItem,
  PantryBulkResult,
  PantryConfirmItem,
  PantryConfirmResult,
  PantryFromTextResult,
  PantryInput,
  PantryItem,
  PantryScanResult,
  Recipe,
  RecipeCookItem,
  RecipeCookResult,
  RecipeFilters,
  RecipeTagUpdate,
  User,
} from './types'

const API_BASE = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '')
const REFRESH_KEY = 'recipe-finder.refresh-token'
let accessToken: string | null = null
let refreshPromise: Promise<string | null> | null = null
const sessionClearedListeners = new Set<() => void>()

export class ApiError extends Error {
  status: number
  body?: unknown

  constructor(message: string, status: number, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function storedRefreshToken() {
  return typeof window === 'undefined' ? null : window.localStorage.getItem(REFRESH_KEY)
}

function saveTokens(tokens: Partial<AuthTokens>) {
  if (tokens.access_token) accessToken = tokens.access_token
  if (tokens.refresh_token && typeof window !== 'undefined') {
    window.localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
  }
}

export function clearSession() {
  accessToken = null
  if (typeof window !== 'undefined') window.localStorage.removeItem(REFRESH_KEY)
  sessionClearedListeners.forEach((listener) => listener())
}

export function onSessionCleared(listener: () => void) {
  sessionClearedListeners.add(listener)
  return () => {
    sessionClearedListeners.delete(listener)
  }
}

async function parseError(response: Response) {
  const body = await response.json().catch(() => undefined)
  const detail = body?.detail
  const message = Array.isArray(detail)
    ? detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(', ')
    : detail || body?.message || `Request failed (${response.status})`
  return new ApiError(message, response.status, body)
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = storedRefreshToken()
  if (!refreshToken) return null
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (response) => {
        if (!response.ok) throw await parseError(response)
        const tokens = (await response.json()) as AuthTokens
        saveTokens(tokens)
        return tokens.access_token
      })
      .catch(() => {
        clearSession()
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

interface RequestOptions extends RequestInit {
  auth?: boolean
  retry?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true, retry = true, headers, ...init } = options
  const requestHeaders = new Headers(headers)
  if (init.body != null && !(init.body instanceof FormData) && !requestHeaders.has('Content-Type')) {
    requestHeaders.set('Content-Type', 'application/json')
  }
  if (auth && accessToken) requestHeaders.set('Authorization', `Bearer ${accessToken}`)

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: requestHeaders })
  if (response.status === 401 && auth && retry) {
    const token = await refreshAccessToken()
    if (token) return request<T>(path, { ...options, retry: false })
  }
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function queryString(values: object) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value === undefined || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== undefined && item !== '') params.append(key, String(item))
      })
      return
    }
    params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

function page<T>(data: CursorPage<T> | T[]): CursorPage<T> {
  return Array.isArray(data) ? { items: data, next_cursor: null, total: data.length } : data
}

export const authApi = {
  async register(input: { email: string; password: string; name?: string }) {
    const response = await request<AuthResponse>('/auth/register', {
      method: 'POST',
      auth: false,
      body: JSON.stringify(input),
    })
    saveTokens(response)
    return response
  },
  async login(input: { email: string; password: string }) {
    const response = await request<AuthResponse>('/auth/login', {
      method: 'POST',
      auth: false,
      body: JSON.stringify(input),
    })
    saveTokens(response)
    return response
  },
  me: () => request<User>('/auth/me'),
  async restore() {
    if (!storedRefreshToken()) return null
    const token = await refreshAccessToken()
    return token ? request<User>('/auth/me') : null
  },
  async logout() {
    const refresh_token = storedRefreshToken()
    try {
      if (refresh_token) {
        await request<void>('/auth/logout', {
          method: 'POST',
          body: JSON.stringify({ refresh_token }),
        })
      }
    } catch {
      // Logging out locally must still succeed when the API is unavailable.
    } finally {
      clearSession()
    }
  },
  async changePassword(input: { current_password: string; new_password: string }) {
    const response = await request<AuthResponse>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify(input),
    })
    saveTokens(response)
    return response
  },
}

export const recipesApi = {
  async list(filters: RecipeFilters = {}) {
    return page(await request<CursorPage<Recipe> | Recipe[]>(`/recipes${queryString(filters)}`))
  },
  get: (id: string) => request<Recipe>(`/recipes/${encodeURIComponent(id)}`),
  update: (id: string, input: RecipeTagUpdate) =>
    request<Recipe>(`/recipes/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    }),
  cook: (id: string, items?: RecipeCookItem[]) =>
    request<RecipeCookResult>(`/recipes/${encodeURIComponent(id)}/cook`, {
      method: 'POST',
      body: JSON.stringify(items === undefined ? {} : { items }),
    }),
  async imageBlob(id: string) {
    const response = await fetch(`${API_BASE}/recipes/${encodeURIComponent(id)}/image`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
    })
    if (response.status === 401) {
      const token = await refreshAccessToken()
      if (!token) throw new ApiError('Unauthorized', 401)
      const retry = await fetch(`${API_BASE}/recipes/${encodeURIComponent(id)}/image`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!retry.ok) throw await parseError(retry)
      return retry.blob()
    }
    if (!response.ok) throw await parseError(response)
    return response.blob()
  },
}

export const pantryApi = {
  async list() {
    return page(await request<CursorPage<PantryItem> | PantryItem[]>('/pantry'))
  },
  create: (input: PantryInput) =>
    request<PantryItem>('/pantry', { method: 'POST', body: JSON.stringify(input) }),
  createBulk: (items: PantryBulkItem[]) =>
    request<PantryBulkResult>('/pantry/bulk', {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),
  fromText: (text: string) =>
    request<PantryFromTextResult>('/pantry/from-text', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  scan: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<PantryScanResult>('/pantry/scan', { method: 'POST', body })
  },
  scanReceipt: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<PantryScanResult>('/pantry/scan-receipt', { method: 'POST', body })
  },
  confirm: (items: PantryConfirmItem[]) =>
    request<PantryConfirmResult>('/pantry/confirm', {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),
  confirmReceipt: (items: PantryConfirmItem[]) =>
    request<PantryConfirmResult>('/pantry/confirm-receipt', {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),
  update: (id: string, input: Partial<PantryInput>) =>
    request<PantryItem>(`/pantry/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    }),
  remove: (id: string) =>
    request<void>(`/pantry/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

export const ingredientsApi = {
  common: () => request<CommonIngredient[]>('/ingredients/common'),
  async search(query: string) {
    return page(
      await request<CursorPage<Ingredient> | Ingredient[]>(
        `/ingredients${queryString({ query })}`,
      ),
    )
  },
}

export const cookbooksApi = {
  async list() {
    return page(await request<CursorPage<Cookbook> | Cookbook[]>('/cookbooks'))
  },
  upload: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<Cookbook>('/cookbooks', { method: 'POST', body })
  },
  get: (id: string) => request<Cookbook>(`/cookbooks/${encodeURIComponent(id)}`),
  retry: (id: string) =>
    request<Cookbook>(`/cookbooks/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  remove: (id: string) =>
    request<void>(`/cookbooks/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  async coverBlob(id: string) {
    const response = await fetch(`${API_BASE}/cookbooks/${encodeURIComponent(id)}/cover`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
    })
    if (response.status === 401) {
      const token = await refreshAccessToken()
      if (!token) throw new ApiError('Unauthorized', 401)
      const retry = await fetch(`${API_BASE}/cookbooks/${encodeURIComponent(id)}/cover`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!retry.ok) throw await parseError(retry)
      return retry.blob()
    }
    if (!response.ok) throw await parseError(response)
    return response.blob()
  },
}

export const apiConfig = { baseUrl: API_BASE }

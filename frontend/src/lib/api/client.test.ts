import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authApi, clearSession, onSessionCleared, recipesApi } from './client'

describe('API client authentication', () => {
  beforeEach(() => {
    clearSession()
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('refreshes once and retries a request after a 401', async () => {
    localStorage.setItem('recipe-finder.refresh-token', 'refresh-token')
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Expired' }), { status: 401 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: 'new-access', refresh_token: 'new-refresh' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    await expect(recipesApi.list()).resolves.toMatchObject({ items: [] })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get('Authorization')).toBe(
      'Bearer new-access',
    )
  })

  it('does not add a content type to bodyless requests', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await recipesApi.list()

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has('Content-Type')).toBe(false)
  })

  it('clears the local session when the logout request fails', async () => {
    localStorage.setItem('recipe-finder.refresh-token', 'refresh-token')
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Network unavailable'))

    await expect(authApi.logout()).resolves.toBeUndefined()
    expect(localStorage.getItem('recipe-finder.refresh-token')).toBeNull()
  })

  it('notifies the auth layer when token refresh fails', async () => {
    localStorage.setItem('recipe-finder.refresh-token', 'expired-refresh-token')
    const sessionCleared = vi.fn()
    const unsubscribe = onSessionCleared(sessionCleared)
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Expired' }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Revoked' }), { status: 401 }))

    await expect(recipesApi.list()).rejects.toMatchObject({ status: 401 })

    expect(sessionCleared).toHaveBeenCalledOnce()
    unsubscribe()
  })

  it('stores the rotated token pair after a password change', async () => {
    localStorage.setItem('recipe-finder.refresh-token', 'old-refresh')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: 'fresh-access',
          refresh_token: 'fresh-refresh',
          token_type: 'bearer',
          expires_in: 900,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await authApi.changePassword({
      current_password: 'correct-horse-battery',
      new_password: 'new-correct-horse-42',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/auth/change-password'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(localStorage.getItem('recipe-finder.refresh-token')).toBe('fresh-refresh')
  })
})

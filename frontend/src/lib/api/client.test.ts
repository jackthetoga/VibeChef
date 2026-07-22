import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authApi, clearSession, onSessionCleared, pantryApi, recipesApi } from './client'

describe('API client authentication', () => {
  beforeEach(() => {
    clearSession()
    vi.restoreAllMocks()
  })

  it('refreshes once and retries a request after a 401', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Expired' }), { status: 401 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: 'new-access' }),
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
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
    })
    expect(fetchMock.mock.calls[1][1]?.body).toBeUndefined()
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
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Network unavailable'))

    await expect(authApi.logout()).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('notifies the auth layer when token refresh fails', async () => {
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
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: 'fresh-access',
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
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
  })

  it('restores a session through the cookie-backed refresh endpoint', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'restored-access' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'user-1', email: 'chef@example.com' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    await expect(authApi.restore()).resolves.toMatchObject({ id: 'user-1' })
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      credentials: 'include',
    })
  })

  it('requests ranked ingredient sets with the selected size', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          item_count: 3,
          candidate_count: 20,
          quality_excluded_recipe_count: 0,
          items: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    await pantryApi.unlockSets(3, 7)

    expect(fetchMock.mock.calls[0][0]).toEqual(
      expect.stringContaining('/pantry/unlock-sets?size=3&limit=7'),
    )
  })
})

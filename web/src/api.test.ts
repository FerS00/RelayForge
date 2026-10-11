import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

describe('API CSRF renewal', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renews CSRF before each mutation and sends its nonce in the header', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: 'fresh-nonce' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'conversation-1', title: 'Nueva conversación' }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    const conversation = await api.createConversation()

    expect(conversation.id).toBe('conversation-1')
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/auth/csrf', { credentials: 'same-origin' })
    const [, mutation] = fetchMock.mock.calls[1]
    expect(new Headers(mutation?.headers).get('X-CSRF-Token')).toBe('fresh-nonce')
    expect(mutation?.credentials).toBe('same-origin')
  })

  it('shares one CSRF refresh across simultaneous mutations', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: 'shared-nonce' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'conversation-1', title: 'Nueva conversación' }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'conversation-2', title: 'Nueva conversación' }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    await Promise.all([api.createConversation(), api.createConversation()])

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('X-CSRF-Token')).toBe('shared-nonce')
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get('X-CSRF-Token')).toBe('shared-nonce')
  })

  it('does not request CSRF for read-only calls', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response('[]'))
    vi.stubGlobal('fetch', fetchMock)

    await api.conversations()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/conversations', expect.objectContaining({ credentials: 'same-origin' }))
  })
})


it('sends action approval as JSON with exact version, hash and retry key', async () => {
  const fetchMock = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(new Response(JSON.stringify({csrf_token: 'nonce'})))
    .mockResolvedValueOnce(new Response(JSON.stringify({id: 'a', status: 'approved'})))
  vi.stubGlobal('fetch', fetchMock)
  try {
    await api.decideAction('c', {id:'a', turn_id:'t', kind:'write_file', payload:{path:'note.txt'}, operation_hash:'b'.repeat(64), version:2, status:'pending', result:null}, 'approve', 'retry-key')
    const [url, request] = fetchMock.mock.calls[1]
    const headers = new Headers(request?.headers)
    expect(url).toBe('/api/conversations/c/actions/a/decision')
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('Idempotency-Key')).toBe('retry-key')
    expect(JSON.parse(String(request?.body))).toEqual({version:2, operation_hash:'b'.repeat(64), decision:'approve'})
  } finally { vi.unstubAllGlobals() }
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api } from './api'

vi.mock('./api', () => ({
  api: {
    authStatus: vi.fn(),
    conversations: vi.fn(),
    createConversation: vi.fn(),
    messages: vi.fn(),
    send: vi.fn(),
  },
}))

describe('new conversation creation', () => {
  beforeEach(() => {
    window.location.hash = '#/chat'
    vi.mocked(api.authStatus).mockResolvedValue({ authenticated: true })
    vi.mocked(api.conversations).mockResolvedValue([])
  })

  it('shows the API error when creating a conversation fails', async () => {
    vi.mocked(api.createConversation).mockRejectedValueOnce(new Error('Token CSRF inválido.'))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'Nueva conversación' }))

    expect((await screen.findByRole('alert')).textContent).toContain('Token CSRF inválido.')
    expect(api.createConversation).toHaveBeenCalledOnce()
  })
})

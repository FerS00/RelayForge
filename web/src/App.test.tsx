import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api } from './api'

vi.mock('./api', () => ({
  api: {
    authStatus: vi.fn(),
    conversations: vi.fn(),
    chatDefaults: vi.fn(),
    agentStatus: vi.fn(),
    uploadAttachment: vi.fn(),
    createConversation: vi.fn(),
    messages: vi.fn(),
    send: vi.fn(),
  },
}))

afterEach(() => cleanup())

describe('new conversation creation', () => {
  beforeEach(() => {
    window.location.hash = '#/'
    vi.mocked(api.authStatus).mockResolvedValue({ authenticated: true })
    vi.mocked(api.conversations).mockResolvedValue([])
    vi.mocked(api.chatDefaults).mockResolvedValue({ agent: 'codex', model: 'gpt-6-luna', runtime: 'windows-native' })
  })

  it('shows the API error when creating a conversation fails', async () => {
    vi.mocked(api.createConversation).mockRejectedValueOnce(new Error('Token CSRF inválido.'))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: /Nueva conversación/ }))

    expect((await screen.findByRole('alert')).textContent).toContain('Token CSRF inválido.')
    expect(api.createConversation).toHaveBeenCalledOnce()
  })
})


describe('chat is the main screen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.location.hash = '#/'
    vi.mocked(api.authStatus).mockResolvedValue({ authenticated: true })
    vi.mocked(api.conversations).mockResolvedValue([])
    vi.mocked(api.chatDefaults).mockResolvedValue({ agent: 'codex', model: 'gpt-6-luna', runtime: 'windows-native' })
    vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
  })
  afterEach(() => vi.unstubAllGlobals())
  it('shows a composer without a task form and sends the first message', async () => {
    vi.mocked(api.createConversation).mockResolvedValue({ id: 'new-chat', title: 'Chat', updated_at: '', agent: 'codex', model: 'gpt-6-luna' })
    vi.mocked(api.messages).mockResolvedValue({ messages: [], active_step: null })
    vi.mocked(api.send).mockResolvedValue({ message: { id: 'm', step_id: 's', role: 'user', content: 'hola', status: 'complete', ts: '' } })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>)
    const input = await screen.findByLabelText('Mensaje')
    expect(screen.queryByLabelText('Workflow')).toBeNull()
    fireEvent.change(input, { target: { value: 'hola' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await vi.waitFor(() => expect(api.send).toHaveBeenCalledWith('new-chat', 'hola', [], expect.any(String)))
    expect(api.createConversation).toHaveBeenCalledWith({})
  })
})

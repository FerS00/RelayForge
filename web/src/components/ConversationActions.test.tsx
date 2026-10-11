import '@testing-library/jest-dom/vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api, type ChatAction } from '../api'
import { ConversationActions } from './ConversationActions'

vi.mock('../api', () => ({api: {decideAction: vi.fn(), approvals: vi.fn(), decideApproval: vi.fn()}}))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('shows exact action and sends its hash/version on approval', async () => {
  const action: ChatAction = {id: 'a', turn_id: 't', kind: 'write_file', payload: {path: 'C:/test/note.txt', content: 'FARO'}, operation_hash: 'a'.repeat(64), status: 'pending', version: 4, result: null}
  vi.mocked(api.decideAction).mockResolvedValue({...action, status: 'approved'})
  render(<QueryClientProvider client={new QueryClient()}><ConversationActions conversation="c" actions={[action]} jobs={[]} /></QueryClientProvider>)
  expect(screen.getByText(/C:\/test\/note.txt/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: 'Aprobar acción'}))
  await waitFor(() => expect(api.decideAction).toHaveBeenCalledWith('c', action, 'approve', expect.any(String)))
  expect(api.decideApproval).not.toHaveBeenCalled()
})

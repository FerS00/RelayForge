import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, it, vi } from 'vitest'
import { api, type Conversation } from '../api'
import { ConversationSettings } from './ConversationSettings'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const conversation: Conversation = {
  id: 'c1', title: 'Chat', updated_at: 't', agent: 'codex', model: 'gpt-small', effort: '', effective_effort: 'medium',
  settings_version: 3, supported_efforts: ['low', 'medium'],
  tools: { write_files: true, commands: true, git_local: true, preview: true, desktop: true, web_search: false, remote_delivery: false },
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ConversationSettings conversation={conversation} /></QueryClientProvider>)
}

it('offers only supported efforts and sends the current settings version', async () => {
  const update = vi.spyOn(api, 'updateConversationSettings').mockResolvedValue({ ...conversation, effort: 'low', settings_version: 4 })
  mount()
  const select = screen.getByRole('combobox', { name: 'Esfuerzo de razonamiento' })
  expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['Predeterminado (medium)', 'low', 'medium'])
  expect(screen.queryByRole('option', { name: 'max' })).not.toBeInTheDocument()
  fireEvent.change(select, { target: { value: 'low' } })
  await waitFor(() => expect(update).toHaveBeenCalledWith('c1', { effort: 'low', settings_version: 3 }))
  expect(await screen.findByText('Se aplica desde tu próximo mensaje.')).toBeInTheDocument()
})

it('toggles a tool and shows a readable error on rejection', async () => {
  const update = vi.spyOn(api, 'updateConversationSettings').mockRejectedValue(new Error('tool_dependency'))
  mount()
  const toggle = screen.getByRole('checkbox', { name: /Entrega remota/ })
  expect(toggle).not.toBeChecked()
  fireEvent.click(toggle)
  await waitFor(() => expect(update).toHaveBeenCalledWith('c1', { tools: { remote_delivery: true }, settings_version: 3 }))
  expect(await screen.findByRole('alert')).toHaveTextContent('La entrega remota requiere Git local activado.')
})

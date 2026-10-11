import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, it, vi } from 'vitest'
import { api, type Agent, type AgentStatus } from '../api'
import { AgentSelection } from './AgentSelection'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const status: AgentStatus[] = ['codex', 'antigravity'].map((agent) => ({
  agent: agent as Agent, status: 'AVAILABLE', auth: 'AVAILABLE', version: 'fixture',
  models: agent === 'codex' ? ['fixture-codex', 'fixture-codex'] : ['fixture-audit'], health: null,
  usage: { turns: 0, steps: 0, input_tokens: null, output_tokens: null,
    five_hour: { status: 'unknown', remaining: null }, weekly: { status: 'unknown', remaining: null } },
}))

function Form({ initialModel = '' }: { initialModel?: string }) {
  const [agent, setAgent] = useState<Agent>('codex')
  const [model, setModel] = useState(initialModel)
  return <AgentSelection agent={agent} model={model} label="prueba" allowed={['codex', 'antigravity']}
    onAgent={setAgent} onModel={setModel} />
}

function mount(initialModel = '') {
  vi.spyOn(api, 'agentStatus').mockResolvedValue(status)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><Form initialModel={initialModel} /></QueryClientProvider>)
}

it('uses an optional select, deduplicates models and resets selection when the agent changes', async () => {
  mount()
  await screen.findByRole('option', { name: 'fixture-codex' })
  const model = screen.getByRole('combobox', { name: 'Modelo de prueba' })
  expect(model).toHaveValue('')
  expect(screen.getAllByRole('option', { name: 'fixture-codex' })).toHaveLength(1)
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  fireEvent.change(model, { target: { value: 'fixture-codex' } })
  expect(model).toHaveValue('fixture-codex')
  fireEvent.change(screen.getByLabelText('Agente de prueba'), { target: { value: 'antigravity' } })
  expect(model).toHaveValue('')
  expect(await screen.findByRole('option', { name: 'fixture-audit' })).toBeInTheDocument()
})

it('keeps a saved model visible without offering it as a catalog choice', async () => {
  mount('saved-model')
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Modelo de prueba' })).toHaveValue('saved-model'))
  expect(screen.getByRole('option', { name: 'saved-model · guardado, fuera del catálogo' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Modelo de prueba'), { target: { value: '' } })
  expect(screen.getByLabelText('Modelo de prueba')).toHaveValue('')
})

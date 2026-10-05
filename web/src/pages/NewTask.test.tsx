import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type Job } from '../api'
import { NewTask } from './NewTask'

const job: Job = {
  id: 'job-2', number: 2, display_id: 'JOB-000002', title: 'Fixture', request_text: 'Make a plan',
  workflow: 'plan', status: 'QUEUED', conversation_id: 'conversation-2', repository_id: null, base_sha: null,
  branch: null, codex_thread_id: null, created_at: 't1', updated_at: 't1',
  finished_at: null, version: 0, error_code: null, error_message: null, retry_at: null, retry_count: 0, plan: null,
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('NewTask', () => {
  it('dispatches the selected planning agent and model', async () => {
    vi.spyOn(api, 'repositories').mockResolvedValue([])
    vi.spyOn(api, 'agentStatus').mockResolvedValue([])
    const create = vi.spyOn(api, 'createJob').mockResolvedValue({ job })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/jobs/new']}><Routes><Route path="/jobs/new" element={<NewTask />} /><Route path="/jobs/:id" element={<p>Created</p>} /></Routes></MemoryRouter></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Solicitud'), { target: { value: 'Plan selected model' } })
    fireEvent.change(screen.getByLabelText('Agente de planificación'), { target: { value: 'codex' } })
    fireEvent.change(screen.getByLabelText('Modelo de planificación'), { target: { value: 'fixture-model' } })
    fireEvent.click(screen.getByRole('button', { name: 'Crear Job de planificación' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('', 'Plan selected model', undefined, 'auto', {
      agent: 'codex', model: 'fixture-model', implementation_model: undefined, audit_model: undefined, require_plan_approval: false,
    }))
  })
  it('submits the requested title and text, then opens Job Detail', async () => {
    const create = vi.spyOn(api, 'createJob').mockResolvedValue({ job })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/jobs/new']}>
      <Routes><Route path="/jobs/new" element={<NewTask />} /><Route path="/jobs/:id" element={<p>Job detail route</p>} /></Routes>
    </MemoryRouter></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Título (opcional)'), { target: { value: 'Fixture title' } })
    fireEvent.change(screen.getByLabelText('Solicitud'), { target: { value: 'Make a plan' } })
    fireEvent.click(screen.getByRole('button', { name: 'Crear Job de planificación' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('Fixture title', 'Make a plan', undefined, 'auto', {
      agent: 'claude', model: undefined, implementation_model: undefined, audit_model: undefined, require_plan_approval: false,
    }))
    expect(await screen.findByText('Job detail route')).toBeInTheDocument()
  })
})

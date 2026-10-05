import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type Job } from '../api'
import { JobDetail } from './JobDetail'

class FakeEventSource {
  close = vi.fn()
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  addEventListener = vi.fn()
  constructor() {}
}

const job: Job = {
  id: 'job-3', number: 3, display_id: 'JOB-000003', title: 'Fixture', request_text: 'Plan this',
  workflow: 'plan', status: 'COMPLETED', conversation_id: 'conversation-3', repository_id: null, base_sha: null,
  branch: null, codex_thread_id: null, created_at: 't1', updated_at: 't2',
  finished_at: 't2', version: 3, error_code: null, error_message: null, retry_at: null, retry_count: 0,
  plan: { objective: 'Objective', summary: 'Summary text', steps: ['First step'], risks: [] },
  steps: [], events: [
    { seq: 5, ts: 't2', type: 'job.state_changed', actor: 'core', data: { from: 'PLANNING', to: 'COMPLETED' } },
    { seq: 6, ts: 't3', type: 'checks.result', actor: 'checks', data: { name: 'pytest', status: 'passed', counts: { passed: 5, failed: 0, skipped: 1 } } },
  ],
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('JobDetail', () => {
  it('offers an explicit Codex handoff for a quota failure', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const paused: Job = { ...job, status: 'WAITING_AGENT', planning_agent: 'claude', paused_stage: 'plan', error_code: 'rate_limited', error_message: 'Límite de uso alcanzado.' }
    vi.spyOn(api, 'job').mockResolvedValue(paused)
    vi.spyOn(api, 'agentStatus').mockResolvedValue([])
    const dispatch = vi.spyOn(api, 'dispatchStep').mockResolvedValue({ ...paused, status: 'QUEUED' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/jobs/job-3']}><Routes><Route path="/jobs/:id" element={<JobDetail />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('alert')).toHaveTextContent('Límite de uso alcanzado.')
    fireEvent.click(screen.getByRole('button', { name: 'Continuar con Codex' }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith('job-3', 'codex', undefined, 3))
  })
  it('shows the plan, terminal status, and persisted activity', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.spyOn(api, 'job').mockResolvedValue(job)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={['/jobs/job-3']}>
      <Routes><Route path="/jobs/:id" element={<JobDetail />} /></Routes>
    </MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('Objective')).toBeInTheDocument()
    expect(screen.getByText('Summary text')).toBeInTheDocument()
    expect(screen.getByText('PLANNING → COMPLETED')).toBeInTheDocument()
    expect(screen.getByText('Check pytest: passed · 5 passed, 0 failed, 1 skipped')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancelar' })).toBeNull()
  })
})

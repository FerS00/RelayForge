import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type Job } from '../api'
import { Dashboard } from './Dashboard'

const job: Job = {
  id: 'job-1', number: 1, display_id: 'JOB-000001', title: 'Fixture job', request_text: 'Plan this',
  workflow: 'plan', status: 'COMPLETED', conversation_id: 'conversation-1', repository_id: null, base_sha: null,
  branch: null, codex_thread_id: null, created_at: 't1', updated_at: 't2',
  finished_at: 't2', version: 3, error_code: null, error_message: null, retry_at: null, retry_count: 0, plan: null,
}

afterEach(() => vi.restoreAllMocks())

describe('Dashboard', () => {
  it('lists Jobs and links to creation and detail', async () => {
    vi.spyOn(api, 'jobs').mockResolvedValue([job])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter><Dashboard /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('link', { name: /JOB-000001 · Fixture job/ })).toHaveAttribute('href', '/jobs/job-1')
    expect(screen.getByRole('link', { name: 'Nueva tarea' })).toHaveAttribute('href', '/jobs/new')
  })
})

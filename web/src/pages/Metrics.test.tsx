import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { Metrics } from './Metrics'

const summary = {
  from: null, to: null, total_jobs: 5, jobs_by_status: { COMPLETED: 3, FAILED: 2 },
  jobs_by_workflow: { feature: 4, trivial: 1 }, average_job_duration_seconds: 12,
  retry_count: 1, step_count: 7, failed_steps: 2, steps_by_agent: {},
  checks: { passed: 4, failed: 1, skipped: 0 }, findings_by_severity: { Medio: 2 },
}

afterEach(() => vi.restoreAllMocks())

describe('Metrics', () => {
  it('shows the aggregate summary', async () => {
    vi.spyOn(api, 'metrics').mockResolvedValue(summary)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter><Metrics /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText(/5 Jobs/)).toBeInTheDocument()
    expect(screen.getByText(/4 pasaron, 1 fallaron/)).toBeInTheDocument()
  })
})

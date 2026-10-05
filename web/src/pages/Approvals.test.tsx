import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Approvals } from './Approvals'

const { approvals, decideApproval } = vi.hoisted(() => ({ approvals: vi.fn(), decideApproval: vi.fn() }))
vi.mock('../api', () => ({ api: { approvals, decideApproval } }))

describe('Approvals', () => {
  beforeEach(() => {
    approvals.mockReset()
    decideApproval.mockReset()
    approvals.mockResolvedValue([{
      id: 'approval-1', job_id: 'job-1', operation: { target: 'origin:refs/heads/agent/job-1', message: 'Job 1' },
      operation_hash: 'op', diff_hash: 'diff', status: 'pending', decision: null, reason: null,
      overlaps: [{ job_id: 'job-2', paths: ['src/shared.py'] }],
    }])
  })

  it('shows the overlapping paths and lets the user approve once', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><Approvals /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText(/src\/shared\.py/)).toBeTruthy()
    decideApproval.mockResolvedValue({})
    fireEvent.click(screen.getByRole('button', { name: 'Approve once' }))
    await waitFor(() => expect(decideApproval).toHaveBeenCalledWith('approval-1', 'approve', 'once'))
  })
})

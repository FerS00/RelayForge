import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../api'
import { Projects } from './Projects'

afterEach(() => vi.restoreAllMocks())

it('opens persistent job history for the selected project', async () => {
  vi.spyOn(api, 'repositories').mockResolvedValue([{ id: 'repo-1', name: 'Project One', path: '/repo', default_branch: 'main', created_at: 't1', enabled: true, dirty: false, health: 'READY', check_commands: [] }])
  const jobs = vi.spyOn(api, 'jobs').mockResolvedValue([{ id: 'job-1', number: 1, display_id: 'JOB-000001', title: 'Build feature', request_text: 'Implement feature', status: 'WAITING_AGENT', planning_agent: 'claude', workflow: 'feature', repository_id: 'repo-1', conversation_id: 'c1', base_sha: 'abc', branch: 'agent/job-1', worktree_path: '/worktree', codex_thread_id: null, created_at: 't1', updated_at: 't2', finished_at: null, version: 3, error_code: 'rate_limited', error_message: 'Quota', retry_at: null, retry_count: 0, plan: null }])
  vi.spyOn(api, 'agentStatus').mockResolvedValue([])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/projects/repo-1']}><Routes><Route path="/projects/:id" element={<Projects />} /></Routes></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('heading', { name: 'Project One' })).toBeInTheDocument()
  expect(await screen.findByRole('link', { name: /JOB-000001/ })).toHaveAttribute('href', '/jobs/job-1')
  expect(jobs).toHaveBeenCalledWith('repo-1')
  expect(screen.getByRole('link', { name: 'Nueva tarea' })).toHaveAttribute('href', '/jobs/new?repository_id=repo-1')
  expect(screen.getByText(/worktree: \/worktree/)).toBeInTheDocument()
})

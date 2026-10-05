import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type Repository } from '../api'
import { Repositories } from './Repositories'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Repositories', () => {
  it('creates a local repository and refreshes the list', async () => {
    const repositories = vi.spyOn(api, 'repositories').mockResolvedValue([])
    const addRepository = vi.fn().mockResolvedValue({ repository: {} })
    vi.spyOn(api, 'addRepository').mockImplementation(addRepository)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><Repositories /></MemoryRouter></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'sample' } })
    fireEvent.change(screen.getByLabelText('Acción'), { target: { value: 'create' } })
    fireEvent.click(screen.getByRole('button', { name: 'Crear repositorio' }))
    await waitFor(() => expect(addRepository).toHaveBeenCalledWith({ mode: 'create', name: 'sample', check_commands: [] }))
    expect(repositories).toHaveBeenCalledTimes(2)
  })

  it('stores argv checks as structured repository configuration', async () => {
    const repository: Repository = {
      id: 'repo-1', name: 'checked', path: 'C:/checked', default_branch: 'main', created_at: 't1',
      enabled: true, dirty: false, check_commands: [],
    }
    const addRepository = vi.spyOn(api, 'addRepository').mockResolvedValue({ repository })
    vi.spyOn(api, 'repositories').mockResolvedValue([])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><Repositories /></MemoryRouter></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: 'checked' } })
    fireEvent.change(screen.getByLabelText('Acción'), { target: { value: 'create' } })
    fireEvent.change(screen.getByLabelText('Checks declarados (JSON argv)'), {
      target: { value: '[{"name":"pytest","argv":["uv","run","pytest","-q"],"timeout_seconds":30}]' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Crear repositorio' }))
    await waitFor(() => expect(addRepository).toHaveBeenCalledWith({
      mode: 'create',
      name: 'checked',
      check_commands: [{ name: 'pytest', argv: ['uv', 'run', 'pytest', '-q'], timeout_seconds: 30 }],
    }))
  })
})

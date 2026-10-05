import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { Pairing } from './Pairing'

afterEach(() => vi.restoreAllMocks())

describe('Pairing', () => {
  it('requests a CSRF nonce and submits the one-time code', async () => {
    const csrf = vi.spyOn(api, 'csrf').mockResolvedValue({ csrf_token: 'nonce' })
    const pair = vi.spyOn(api, 'pair').mockResolvedValue({ authenticated: true })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><Pairing /></QueryClientProvider>)
    await waitFor(() => expect(csrf).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('Código de un solo uso'), { target: { value: 'single-use-code' } })
    fireEvent.click(screen.getByRole('button', { name: 'Emparejar' }))
    await waitFor(() => expect(pair).toHaveBeenCalledWith('single-use-code', 'nonce'))
  })
})

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, type PreviewList } from '../api'
import { Deliverables } from './Deliverables'

vi.mock('../api', () => ({
  api: {
    fileRoots: vi.fn(),
    previews: vi.fn(),
    files: vi.fn(),
    previewTicket: vi.fn(),
    stopPreview: vi.fn(),
    fileContentUrl: vi.fn(() => '/content'),
    fileZipUrl: vi.fn(() => '/zip'),
  },
}))

const runningPreview: PreviewList['items'][number] = {
  id: 'p1',
  status: 'running',
  kind: 'static',
  root: 'workspace',
  path: 'site',
  port: null,
  error_code: null,
  created_at: '2026-10-09T00:00:00Z',
  log_tail: [],
}

beforeEach(() => {
  vi.mocked(api.fileRoots).mockResolvedValue({ roots: [{ id: 'workspace', name: 'Workspace' }] })
  vi.mocked(api.previews).mockResolvedValue({ items: [runningPreview], available: true, error_code: null })
  vi.mocked(api.files).mockResolvedValue({
    root: 'workspace',
    path: '',
    entries: [{ name: 'src', directory: true, size_bytes: 0, modified_at: '2026-10-09T00:00:00Z' }],
    truncated: false,
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

it('shows preview state and browses directories under the selected root', async () => {
  vi.mocked(api.files).mockResolvedValueOnce({
    root: 'workspace',
    path: '',
    entries: [{ name: 'src', directory: true, size_bytes: 0, modified_at: '2026-10-09T00:00:00Z' }],
    truncated: false,
  }).mockResolvedValueOnce({
    root: 'workspace',
    path: 'src',
    entries: [{ name: 'main.ts', directory: false, size_bytes: 40, modified_at: '2026-10-09T00:00:00Z' }],
    truncated: false,
  })

  render(<Deliverables conversationId="c1" onClose={vi.fn()} />)

  expect(await screen.findByText('En ejecución')).toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: 'Carpeta: src' }))
  await waitFor(() => expect(api.files).toHaveBeenLastCalledWith('c1', 'workspace', 'src'))
  expect(await screen.findByRole('link', { name: 'Archivo: main.ts' })).toHaveAttribute('href', '/content')
  expect(screen.getByRole('link', { name: 'Descargar ZIP' })).toHaveAttribute('href', '/zip')
})

it('opens a preview in the sandboxed inline frame with a one-use ticket', async () => {
  vi.mocked(api.previewTicket).mockResolvedValue({ url: 'https://relayforge.example.test:8443/__rf/open/ticket', expires_in: 120 })
  render(<Deliverables conversationId="c1" onClose={vi.fn()} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Ver aquí' }))

  const frame = await screen.findByTitle('Preview de la conversación')
  expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-forms allow-same-origin allow-popups')
  expect(frame).toHaveAttribute('src', 'https://relayforge.example.test:8443/__rf/open/ticket')
  expect(api.previewTicket).toHaveBeenCalledWith('p1')
})

it('reports an unavailable gateway and stops a running preview', async () => {
  vi.mocked(api.previews).mockResolvedValue({
    items: [runningPreview],
    available: false,
    error_code: 'preview_gateway_unavailable',
  })
  vi.mocked(api.stopPreview).mockResolvedValue({ id: 'p1', status: 'stopped' })
  render(<Deliverables conversationId="c1" onClose={vi.fn()} />)

  expect(await screen.findByText('preview_gateway_unavailable')).toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: 'Detener' }))
  await waitFor(() => expect(api.stopPreview).toHaveBeenCalledWith('p1'))
})

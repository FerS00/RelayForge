import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChatView } from './ChatView'

afterEach(() => cleanup())

describe('ChatView', () => {
  it('does not create DOM elements from raw HTML', () => {
    render(<ChatView messages={[{ id: '1', step_id: 's', role: 'orchestrator', content: '<img src=x onerror=alert(1)>', status: 'complete', ts: '' }]} active={false} onSend={vi.fn()} onMenu={vi.fn()} />)
    expect(document.querySelector('img')).toBeNull()
  })

  it('renders markdown while rejecting unsafe links and raw HTML', () => {
    render(<ChatView messages={[{ id: '1', step_id: 's', role: 'orchestrator', content: '[click](javascript:alert(1))\n\n<script>alert(1)</script>\n\n**safe**', status: 'complete', ts: '' }]} active={false} onSend={vi.fn()} onMenu={vi.fn()} />)
    expect(screen.getByText('safe').tagName).toBe('STRONG')
    expect(document.querySelector('script')).toBeNull()
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull()
  })
})


describe('chat evidence and retries', () => {
  it('preserves draft and files after send failure', async () => {
    const send = vi.fn().mockRejectedValue(new Error('Error de red'))
    render(<ChatView messages={[]} active={false} onSend={send} onMenu={vi.fn()} agent="Codex" />)
    fireEvent.change(screen.getByLabelText('Mensaje'), { target: { value: 'Revisa esta evidencia' } })
    const file = new File(['error log'], 'error.log', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('Adjuntar evidencia'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Error de red')
    expect(screen.getByLabelText('Mensaje')).toHaveValue('Revisa esta evidencia')
    expect(screen.getByText('error.log')).toBeInTheDocument()
    expect(send).toHaveBeenCalledWith('Revisa esta evidencia', [file])
  })

  it('sends an attachment without requiring text and clears after success', async () => {
    const send = vi.fn().mockResolvedValue(undefined)
    render(<ChatView messages={[]} active={false} onSend={send} onMenu={vi.fn()} />)
    const file = new File(['log'], 'test.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('Adjuntar evidencia'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await waitFor(() => expect(send).toHaveBeenCalledWith('', [file]))
    await waitFor(() => expect(screen.queryByText('test.txt')).toBeNull())
  })

  it('does not send Enter while composing text with IME', () => {
    const send = vi.fn()
    render(<ChatView messages={[]} active={false} onSend={send} onMenu={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Mensaje'), { target: { value: 'draft' } })
    fireEvent.keyDown(screen.getByLabelText('Mensaje'), { key: 'Enter', isComposing: true })
    expect(send).not.toHaveBeenCalled()
  })
})


it('allows sending a new message while the agent is working', async () => {
  const send = vi.fn().mockResolvedValue(undefined)
  render(<ChatView messages={[]} active={true} onSend={send} onMenu={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Mensaje'), {target: {value: 'Un detalle adicional'}})
  fireEvent.click(screen.getByRole('button', {name: 'Enviar'}))
  await waitFor(() => expect(send).toHaveBeenCalledWith('Un detalle adicional', []))
})

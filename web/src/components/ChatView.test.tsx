import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChatView } from './ChatView'

describe('ChatView', () => {
  it('renders untrusted content as text', () => {
    render(<ChatView messages={[{ id: '1', step_id: 's', role: 'orchestrator', content: '<img src=x onerror=alert(1)>', status: 'complete', ts: '' }]} active={false} onSend={vi.fn()} onMenu={vi.fn()} />)
    expect(screen.getByText('<img src=x onerror=alert(1)>').textContent).toBe('<img src=x onerror=alert(1)>')
    expect(document.querySelector('img')).toBeNull()
  })
})

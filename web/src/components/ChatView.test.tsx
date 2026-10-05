import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChatView } from './ChatView'

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

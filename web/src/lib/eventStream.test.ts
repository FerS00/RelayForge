import { renderHook, act } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useEventStream } from './eventStream'

class FakeEventSource {
  static instance: FakeEventSource
  listeners: Record<string, (event: Event) => void> = {}
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) { FakeEventSource.instance = this }
  addEventListener(type: string, listener: (event: Event) => void) { this.listeners[type] = listener }
  close() { this.closed = true }
  emit(type: string, data: string) { this.listeners[type]?.({ data } as MessageEvent<string>) }
}

describe('useEventStream', () => {
  afterEach(() => { vi.unstubAllGlobals() })
  it('deduplicates conversation events by sequence and closes on unmount', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const onEvent = vi.fn()
    const { unmount } = renderHook(() => useEventStream('c1', onEvent, vi.fn()))
    const stream = FakeEventSource.instance
    const event = JSON.stringify({ conversation: 'c1', seq: 2, type: 'agent.message', data: { text: 'ok' } })
    act(() => { stream.emit('conversation.event', event); stream.emit('conversation.event', event) })
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(stream.url).toBe('/api/stream?conversation=c1')
    unmount()
    expect(stream.closed).toBe(true)
  })
})

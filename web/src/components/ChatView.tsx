import { useState, type FormEvent, type KeyboardEvent } from 'react'
import type { Message } from '../api'
import styles from '../styles.module.css'

type Props = { messages: Message[]; active: boolean; onSend: (text: string) => void; error?: string; onMenu: () => void }

export function ChatView({ messages, active, onSend, error, onMenu }: Props) {
  const [value, setValue] = useState('')
  const send = (event?: FormEvent) => {
    event?.preventDefault()
    if (!value.trim() || active) return
    onSend(value)
    setValue('')
  }
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }
  return <main className={styles.chat}>
    <header className={styles.chatHeader}><button className={styles.menuButton} onClick={onMenu} aria-label="Abrir conversaciones">☰</button><span>Claude</span></header>
    <section className={styles.messages} aria-live="polite">
      {messages.length === 0 && <div className={styles.empty}><h1>¿En qué puedo ayudarte?</h1><p>Tu conversación se ejecuta en el directorio de trabajo configurado.</p></div>}
      {messages.map((message) => <article key={message.id} className={`${styles.message} ${message.role === 'user' ? styles.userMessage : styles.agentMessage}`}>
        <div className={styles.messageRole}>{message.role === 'user' ? 'Tú' : 'Claude'}</div>
        <div className={styles.messageText}>{message.content}</div>
      </article>)}
      {active && <div className={styles.activity}>Claude está respondiendo…</div>}
      {error && <div role="alert" className={styles.error}>{error}</div>}
    </section>
    <form className={styles.composer} onSubmit={send}>
      <textarea aria-label="Mensaje" placeholder="Escribe un mensaje…" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={keyDown} rows={2} />
      <button type="submit" disabled={active || !value.trim()}>Enviar</button>
      <span>Enter para enviar · Mayús+Enter para una línea nueva</span>
    </form>
  </main>
}

import type { Conversation } from '../api'
import { Link } from 'react-router-dom'
import styles from '../styles.module.css'

type Props = { conversations: Conversation[]; activeId?: string; onSelect: (id: string) => void; onCreate: () => void; onClose: () => void; createError?: string }

export function ConversationList({ conversations, activeId, onSelect, onCreate, onClose, createError }: Props) {
  return <aside className={styles.sidebar} aria-label="Conversaciones">
    <div className={styles.brand}>RelayForge</div>
    <nav className={styles.productNav} aria-label="Navegación principal">
      <Link to="/jobs">Jobs</Link>
      <Link to="/jobs/new">Nueva tarea</Link>
    </nav>
    <button className={styles.newButton} onClick={onCreate}>＋ Nueva conversación</button>
    {createError && <p role="alert" className={styles.error}>{createError}</p>}
    <nav className={styles.conversationNav}>
      {conversations.map((conversation) => <button
        className={`${styles.conversation} ${activeId === conversation.id ? styles.active : ''}`}
        key={conversation.id}
        onClick={() => { onSelect(conversation.id); onClose() }}
      >{conversation.title}</button>)}
    </nav>
  </aside>
}

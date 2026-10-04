import type { Conversation } from '../api'
import styles from '../styles.module.css'

type Props = { conversations: Conversation[]; activeId?: string; onSelect: (id: string) => void; onCreate: () => void; onClose: () => void }

export function ConversationList({ conversations, activeId, onSelect, onCreate, onClose }: Props) {
  return <aside className={styles.sidebar} aria-label="Conversaciones">
    <div className={styles.brand}>RelayForge</div>
    <button className={styles.newButton} onClick={onCreate}>＋ Nueva conversación</button>
    <nav className={styles.conversationNav}>
      {conversations.map((conversation) => <button
        className={`${styles.conversation} ${activeId === conversation.id ? styles.active : ''}`}
        key={conversation.id}
        onClick={() => { onSelect(conversation.id); onClose() }}
      >{conversation.title}</button>)}
    </nav>
  </aside>
}

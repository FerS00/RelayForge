import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import styles from '../styles.module.css'

export function Agents() {
  const query = useQuery({ queryKey: ['doctor'], queryFn: api.doctor })
  const health = useQuery({ queryKey: ['agent-health'], queryFn: api.agents })
  const status = useQuery({ queryKey: ['agent-status'], queryFn: api.agentStatus, staleTime: 30000 })
  return <main className={styles.page}>
    <header className={styles.pageHeader}><div><h1>Estado del sistema</h1><p>Diagnóstico de solo lectura; las salidas de autenticación no se muestran.</p></div><Link className={styles.pageButton} to="/jobs">Volver</Link></header>
    {query.isPending && <p>Consultando…</p>}
    {query.isError && <p role="alert">{query.error.message}</p>}
    {query.data && <dl className={styles.doctorList}>{Object.entries(query.data).map(([name, value]) => <div key={name}><dt>{name}</dt><dd><code>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</code></dd></div>)}</dl>}
    <section className={styles.planSection}>
      <h2>Disponibilidad y consumo</h2>
      {status.data?.map((agent) => <p key={agent.agent}>{agent.agent} {agent.version}: {agent.status} · auth {agent.auth} · {agent.usage.turns} turnos · tokens {agent.usage.input_tokens ?? 'desconocidos'}/{agent.usage.output_tokens ?? 'desconocidos'} · cuota 5 h: desconocida · semanal: desconocida</p>)}
      {status.isError && <p role="status">Disponibilidad sin comprobar.</p>}
      <h2>Salud de agentes</h2>
      {health.isError && <p role="alert">{health.error.message}</p>}
      {health.data?.length ? <dl className={styles.doctorList}>{health.data.map((agent) => <div key={agent.agent}>
        <dt>{agent.agent}</dt><dd>{agent.status}{agent.detail ? ` · ${agent.detail}` : ''}{agent.rate_limited_until ? ` · disponible ${agent.rate_limited_until}` : ''}</dd>
      </div>)}</dl> : <p>Sin fallos recientes registrados.</p>}
    </section>
  </main>
}

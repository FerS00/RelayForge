import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import styles from '../styles.module.css'

export function Projects() {
  const { id } = useParams()
  const repositories = useQuery({ queryKey: ['repos'], queryFn: api.repositories, refetchInterval: 10000 })
  const jobs = useQuery({ queryKey: ['jobs', id], queryFn: () => api.jobs(id), refetchInterval: 3000 })
  const agents = useQuery({ queryKey: ['agent-status'], queryFn: api.agentStatus, staleTime: 30000, refetchInterval: 30000 })
  const selected = repositories.data?.find((repo) => repo.id === id)
  return <main className={styles.page}>
    <header className={styles.pageHeader}>
      <div><h1>{selected?.name ?? 'Proyectos'}</h1><p>Trabajo por agentes en repositorios y worktrees aislados.</p></div>
      <div className={styles.pageActions}>
        <Link className={styles.pageButton} to="/repos">Crear o registrar proyecto</Link>
        <Link className={styles.pageButton} to="/agents">Agentes y diagnóstico</Link>
        <Link className={styles.pageButton} to="/approvals">Aprobaciones</Link>
        <Link className={styles.pageButton} to="/chat">Consulta con Claude</Link>
        <Link className={`${styles.pageButton} ${styles.pageButtonPrimary}`} to={`/jobs/new${id ? `?repository_id=${encodeURIComponent(id)}` : ''}`}>Nueva tarea</Link>
      </div>
    </header>
    <nav aria-label="Proyectos registrados" className={styles.pageActions}>
      <Link to="/" aria-current={!id ? 'page' : undefined}>Todos los proyectos</Link>
      {repositories.data?.map((repo) => <Link key={repo.id} to={`/projects/${repo.id}`} aria-current={repo.id === id ? 'page' : undefined}>
        {repo.name} · {repo.health ?? 'No comprobado'}{repo.dirty ? ' · cambios locales' : ''}
      </Link>)}
    </nav>
    {repositories.isError && <p role="alert">No se pudo consultar la lista de proyectos.</p>}
    {repositories.data?.length === 0 && <p>Registra o crea un proyecto para ejecutar tareas de desarrollo.</p>}
    {id && repositories.data && !selected && <p role="alert">El proyecto no existe o no está disponible.</p>}
    {selected && <p>Rama base: <code>{selected.default_branch}</code> · diagnóstico Git: {selected.health ?? 'No comprobado'} · {selected.check_commands.length} checks declarados.</p>}
    <section className={styles.planSection} aria-label="Uso de agentes">
      <h2>Agentes y consumo registrado</h2>
      {agents.data?.map((agent) => <p key={agent.agent}>{agent.agent}: {agent.health?.status ?? agent.status} · auth {agent.auth} · {agent.usage.turns} turnos registrados · tokens entrada/salida {agent.usage.input_tokens ?? 'desconocidos'}/{agent.usage.output_tokens ?? 'desconocidos'} · cuota 5 h: desconocida · semanal: desconocida</p>)}
      {agents.isError && <p role="status">Estado de agentes sin comprobar.</p>}
    </section>
    <section className={styles.jobList} aria-label="Historial de trabajos">
      <h2>{selected ? `Trabajos de ${selected.name}` : 'Trabajos recientes'}</h2>
      {jobs.isPending && <p>Cargando historial…</p>}
      {jobs.isError && <p role="alert">No se pudo cargar el historial.</p>}
      {jobs.data?.length === 0 && <p>Sin trabajos registrados.</p>}
      {jobs.data?.map((job) => <Link className={styles.jobCard} key={job.id} to={`/jobs/${job.id}`}>
        <span className={styles.jobTitle}>{job.display_id} · {job.title}</span>
        <span>{job.status} · {job.planning_agent ?? 'claude'}</span>
        <span>Objetivo: {job.request_text}</span>
        <span>Rama: {job.branch ?? 'pendiente'} · worktree: {job.worktree_path ?? 'pendiente'}</span>
        <span>Actualizado: {job.updated_at}</span>
      </Link>)}
    </section>
  </main>
}

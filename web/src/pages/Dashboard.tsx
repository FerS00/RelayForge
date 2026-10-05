import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import styles from '../styles.module.css'

export function Dashboard() {
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api.jobs() })
  return <main className={styles.page}>
    <header className={styles.pageHeader}>
      <div><h1>Jobs</h1><p>Planes y actividad de las tareas.</p></div>
      <div className={styles.pageActions}>
        <Link className={styles.pageButton} to="/">Proyectos</Link>
        <Link className={styles.pageButton} to="/repos">Repositories</Link>
        <Link className={styles.pageButton} to="/agents">Estado del sistema</Link>
        <Link className={styles.pageButton} to="/approvals">Aprobaciones</Link>
        <Link className={styles.pageButton} to="/metrics">Métricas</Link>
        <Link className={`${styles.pageButton} ${styles.pageButtonPrimary}`} to="/jobs/new">Nueva tarea</Link>
      </div>
    </header>
    {jobs.isLoading && <p className={styles.muted}>Cargando Jobs…</p>}
    {jobs.isError && <p role="alert">No se pudieron cargar los Jobs.</p>}
    {jobs.data?.length === 0 && <p className={styles.muted}>Todavía no hay Jobs.</p>}
    <section className={styles.jobList} aria-label="Lista de Jobs">
      {jobs.data?.map((job) => <Link className={styles.jobCard} key={job.id} to={`/jobs/${job.id}`}>
        <span className={styles.jobTitle}>{job.display_id} · {job.title}</span>
        <span>{job.status}</span>
        <span className={styles.jobMeta}>{job.workflow} · Actualizado {job.updated_at}</span>
        <span className={styles.jobMeta}>Versión {job.version}</span>
      </Link>)}
    </section>
  </main>
}

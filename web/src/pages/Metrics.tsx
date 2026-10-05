import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import styles from '../styles.module.css'

function nextDay(value: string): string {
  const day = new Date(`${value}T00:00:00Z`)
  day.setUTCDate(day.getUTCDate() + 1)
  return day.toISOString()
}

export function Metrics() {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const fromUtc = from ? `${from}T00:00:00Z` : undefined
  const toUtc = to ? nextDay(to) : undefined
  const query = useQuery({ queryKey: ['metrics', fromUtc, toUtc], queryFn: () => api.metrics(fromUtc, toUtc) })
  return <main className={styles.page}>
    <header className={styles.pageHeader}>
      <div><h1>Métricas</h1><p>Agregados calculados desde Jobs, pasos, checks y hallazgos.</p></div>
      <Link className={styles.pageButton} to="/jobs">Jobs</Link>
    </header>
    <section className={styles.planSection} aria-label="Filtro temporal">
      <label>Desde <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
      <label>Hasta <input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
    </section>
    {query.isPending && <p className={styles.muted}>Cargando métricas…</p>}
    {query.isError && <p role="alert">No se pudieron cargar las métricas: {query.error.message}</p>}
    {query.data && <>
      <section className={styles.planSection}>
        <h2>Jobs</h2>
        <p>{query.data.total_jobs} Jobs · {query.data.step_count} pasos · {query.data.retry_count} reintentos · {query.data.failed_steps} pasos fallidos</p>
        <p>Duración media: {query.data.average_job_duration_seconds === null ? 'sin datos' : `${query.data.average_job_duration_seconds} s`}</p>
        <dl className={styles.doctorList}>{Object.entries(query.data.jobs_by_status).map(([key, count]) => <div key={key}><dt>{key}</dt><dd>{count}</dd></div>)}</dl>
        <h3>Workflows</h3>
        <dl className={styles.doctorList}>{Object.entries(query.data.jobs_by_workflow).map(([key, count]) => <div key={key}><dt>{key}</dt><dd>{count}</dd></div>)}</dl>
      </section>
      <section className={styles.planSection}>
        <h2>Agentes y checks</h2>
        <dl className={styles.doctorList}>{Object.entries(query.data.steps_by_agent).map(([agent, row]) => <div key={agent}><dt>{agent}</dt><dd>{row.steps} pasos · {row.failed} fallidos · {row.duration_seconds.toFixed(2)} s</dd></div>)}</dl>
        <p>Checks: {query.data.checks.passed} pasaron, {query.data.checks.failed} fallaron, {query.data.checks.skipped} omitidos.</p>
        <p>Hallazgos: {Object.entries(query.data.findings_by_severity).map(([severity, count]) => `${severity} ${count}`).join(' · ') || 'ninguno'}</p>
      </section>
    </>}
  </main>
}

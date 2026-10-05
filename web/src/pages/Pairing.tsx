import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api'
import styles from '../styles.module.css'

export function Pairing() {
  const [code, setCode] = useState('')
  const queryClient = useQueryClient()
  const csrf = useQuery({ queryKey: ['csrf'], queryFn: api.csrf })
  const pair = useMutation({
    mutationFn: () => api.pair(code.trim(), csrf.data!.csrf_token),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['auth'] }) },
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    pair.mutate()
  }
  return <main className={styles.welcome}>
    <h1>Emparejar RelayForge</h1>
    <p>Introduce el código temporal generado en el equipo anfitrión.</p>
    <form className={styles.jobForm} onSubmit={submit}>
      <label>Código de un solo uso<input autoComplete="one-time-code" required value={code} onChange={(event) => setCode(event.target.value)} /></label>
      {csrf.isError && <p role="alert">No se pudo iniciar el pairing.</p>}
      {pair.isError && <p role="alert">{pair.error.message}</p>}
      <button className={`${styles.pageButton} ${styles.pageButtonPrimary}`} disabled={!csrf.data || pair.isPending}>Emparejar</button>
    </form>
  </main>
}

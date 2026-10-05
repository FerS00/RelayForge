import { useId } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Agent } from '../api'

const names: Record<Agent, string> = { claude: 'Claude Code', codex: 'Codex CLI', antigravity: 'Antigravity (solo lectura)' }

export function AgentSelection({ agent, model, allowed, label, onAgent, onModel }: {
  agent: Agent; model: string; allowed: Agent[]; label: string
  onAgent: (agent: Agent) => void; onModel: (model: string) => void
}) {
  const id = useId()
  const status = useQuery({ queryKey: ['agent-status'], queryFn: api.agentStatus, staleTime: 30000 })
  const current = status.data?.find((item) => item.agent === agent)
  return <fieldset>
    <legend>{label}</legend>
    <label>Agente de {label}
      <select value={agent} onChange={(event) => { onAgent(event.target.value as Agent); onModel('') }}>
        {allowed.map((item) => <option key={item} value={item}>{names[item]}</option>)}
      </select>
    </label>
    <label>Modelo de {label}
      <input list={id} maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9._:\/\-]*" value={model}
        placeholder="Predeterminado de la CLI" onChange={(event) => onModel(event.target.value)} />
      <datalist id={id}>{current?.models.map((item) => <option key={item} value={item} />)}</datalist>
    </label>
    <p>{current ? `CLI: ${current.status} · autenticación: ${current.auth}` : 'Disponibilidad sin comprobar.'}</p>
    {status.isError && <p role="status">No se pudo consultar la disponibilidad del agente.</p>}
  </fieldset>
}

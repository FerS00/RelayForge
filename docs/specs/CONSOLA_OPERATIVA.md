# Especificación técnica — consola operativa

Estado: alcance funcional autorizado por la especificación del usuario del 2026-10-05; implementación presente en el checkout; auditoría independiente APROBADO para gates locales; aceptación operativa real pendiente. El nuevo plan revisado está en borrador; esta especificación conserva el alcance autorizado previamente. Esta corrección precede a la Fase 11 visual. Claude del host no está autenticado: se aplica la continuidad autorizada, Codex especifica/implementa y Antigravity audita sin editar. La entrega pública queda sujeta a las autorizaciones específicas recibidas para esta tarea y a los límites del plan.

## Objetivo

Usar la laptop encendida como host de una consola móvil de trabajo por proyectos. El flujo sigue siendo planificación Claude (o Codex de relevo, solo lectura), implementación Codex en worktree, checks, auditoría Antigravity solo lectura y aprobación humana. El chat existente queda accesible como consulta secundaria.

## Rutas autorizadas

- Backend: `src/relayforge/adapters/base.py`, `adapters/claude/{adapter.py,parser.py,orchestrator.py}`, `adapters/codex/{adapter.py,planner.py}`, `adapters/antigravity/adapter.py`, `core/{jobs.py,scheduler.py,workflow.py,audit.py,states.py,agent_health.py}`, `db/models.py`, `db/migrations/versions/0008_agent_dispatch.py`, `api/{app.py,schemas.py}`, `api/routes/{jobs.py,agents.py}`, `doctor/checks.py`, `settings.py` (relativas a `src/relayforge`).
- UI: `web/src/{App.tsx,api.ts}`, `web/src/components/AgentSelection.tsx`, `web/src/pages/{Projects.tsx,NewTask.tsx,JobDetail.tsx,Dashboard.tsx,Agents.tsx}`; estilos existentes solo cuando sean necesarios para controles utilizables.
- Verificación: pruebas existentes afectadas de adaptadores, migraciones, estados, API y UI; nuevas `tests/integration/test_agent_dispatch.py`, `tests/unit/test_codex_planner.py`, `web/src/pages/Projects.test.tsx`. Fakes existentes pueden ampliarse, sin CLI real en pruebas.
- Entorno y documentación: `Dockerfile.windows`, `compose.windows.yaml`, `docs/{PLAN_PROYECTO.md,ESTADO_TRABAJO.md,docker-windows.md}`, este documento y README. Graphify se actualiza localmente.

## Datos y contratos

Rutas de diagnóstico directamente requeridas: `src/relayforge/core/repositories.py` y pruebas de repositorios. La UI pide aprobación de plan por defecto mediante `require_plan_approval`; el API conserva la política del workflow para clientes anteriores cuando ese campo es falso/omitido.

- SQLite añade a Job `planning_agent` (claude por defecto), `planning_model`, `implementation_model`, `audit_model` y `paused_stage`; la migración conserva Jobs y datos previos. Cuota/auth deja el Job en `WAITING_AGENT` con la etapa conservada.
- `POST /api/jobs` acepta `agent` y `model` para planificación y modelos opcionales de implementación/auditoría. Antigravity sigue reservado a auditoría de un diff; no se le conceden herramientas de implementación.
- `POST /api/jobs/{id}/step` recibe `agent`, `model` opcionales y `version`. Retoma una etapa detenida por cuota/auth, o ajusta implementación antes de aprobar el plan. Respuesta 409 ante etapa activa, versión obsoleta, rol incompatible o Job terminal no recuperable. El cambio y su motivo se registran en eventos persistentes.
- `GET /api/jobs?repository_id=...` filtra historial persistente. `GET /api/agents/status` expone instalación/auth verificadas con timeout, estado de salud y modelos configurados. Conteos de turnos/tokens provienen de eventos reales; ventanas de cinco horas y semanal son `unknown` cuando el proveedor no las expone. No se leen ni sirven credenciales de perfiles.
- El modelo se pasa como argumento separado `--model`, por invocación; no se muta un adaptador global. Vacío significa modelo predeterminado de la CLI. Modelos configurables por agente, sin catálogo inventado.

## Reglas y casos límite

1. `/` abre proyectos y sus Jobs; registrar/crear repositorio reutiliza el API existente. Recarga conserva selección por URL e historial en SQLite.
2. Planificación en repositorios usa el mismo worktree que recibirá implementación. Relevo reutiliza Job, solicitud, plan/eventos y worktree; no transfiere identificadores de sesión entre proveedores.
3. Cuota/auth se conservan como códigos reconocibles y mensajes claros. El Job espera una decisión de agente; cambiar de agente es explícito. Agentes que implementan no pueden autoaprobarse: auditoría sigue independiente y con límites actuales.
4. Modelo/agente solo pueden cambiar en etapas detenidas o aprobación de plan; no se lanzan dos escritores para un Job. Límite de tres correcciones y aprobaciones de entrega existentes se conservan.
5. Antigravity sigue siendo auditor. Su modelo puede seleccionarse para la etapa auditora; la selección no amplía permisos. La UI muestra fases, eventos, diff y aprobaciones existentes como consola de trabajo.
6. Docker incorpora las tres CLI con credenciales fuera de la imagen y perfiles persistentes. Login interactivo y prueba móvil son pasos separados de build y tests con dobles.

## Criterios de aceptación

1. Crear/registrar proyecto, abrir su historial y despachar Job con agente/modelo elegido; verificar persistencia tras recarga.
2. Fallo simulado de Claude por cuota/auth: error visible y relevo a Codex sobre el mismo Job/worktree; planificación Codex read-only, implementación workspace-write.
3. Modelo seleccionado llega al argv de la CLI y persiste; selecciones incompatibles y carreras devuelven 409/422.
4. Cuotas no expuestas figuran desconocidas; instalación/auth y turnos/tokens tienen evidencia y no exponen secretos.
5. Aprobaciones y auditoría permanecen obligatorias según workflow; no hay commit/push implícito.
6. Migración, suites Python/web, tipos, lint, build, navegador real y auditoría Antigravity se reportan con resultados separados. Docker se reconstruye después de cerrar cambios; login y prueba real quedan pendientes si requieren intervención.

## Verificación prevista

Pruebas con fakes para migración, argv/modelos, failover, persistencia, conflictos, permisos de planificación y métricas. Ruff, mypy, pytest; ESLint, TypeScript, Vitest/build. Navegador real con API local aislada. Build Docker, health y versiones de CLI; luego logins interactivos y una tarea real de desarrollo en repositorio de prueba autorizado.

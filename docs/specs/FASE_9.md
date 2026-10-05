> Especificación histórica. Las referencias numeradas al plan corresponden al [plan anterior archivado](../archive/PLAN_PROYECTO_2026-10-05_PREVIO.md); para alcance/estado y nuevas fases consulta el [plan vigente](../PLAN_PROYECTO.md). Este aviso no cambia sus criterios previamente aprobados.

# Especificación técnica — Fase 9

Estado: Implementada; auditoría pendiente (2026-10-04). Codex especifica e implementa sin Claude; Antigravity audita en solo lectura. Complejidad media-alta por selección de workflow, aprobación del plan y agregados históricos. Antigravity: esfuerzo medium recomendado y aplicado; Codex usa el esfuerzo efectivo del turno.

## Objetivo

Añadir selección `auto|trivial|feature|security`, plantillas YAML validadas, sugerencia estructurada del plan, elevación a `security` por sugerencia o paths sensibles, omisión de auditoría para `trivial`, aprobación humana de plan cuando una plantilla lo exige y métricas agregadas filtrables con una vista web.

## Contratos

- Plantillas admitidas: trivial (sin auditoría), feature (checks y auditoría), security (checks, auditoría reforzada, aprobación del plan). `auto` adopta `suggested_workflow` del plan; nunca permite rebajar una ruta sensible desde security.
- El plan debe incluir `suggested_workflow` validado como trivial/feature/security. El Core guarda workflow efectivo en Job. Paths `auth/**`, `**/auth/**`, `security/**` o `**/security/**` elevan a security al inspeccionar el diff y antes de auditoría; al usar sugerencia security, el plan queda en `WAITING_APPROVAL` antes de implementar.
- Un Job trivial completa tras checks sin ejecutar auditoría. Feature/security conservan la auditoría existente; el perfil security instruye revisión reforzada.
- `GET /api/metrics/summary?from=&to=` devuelve conteos de Jobs, estados, workflows, duración agregada y por agente/paso, fallos, retries, checks y hallazgos dentro del intervalo UTC. Fechas mal formadas o un intervalo invertido se rechazan.
- Métricas calculadas desde Jobs, JobSteps, Findings y eventos; no se persiste un segundo almacén.

## Rutas afectadas

- `docs/specs/FASE_9.md`, `docs/PLAN_PROYECTO.md`, `docs/ESTADO_TRABAJO.md`
- `config/workflows/{trivial.yaml,feature.yaml,security.yaml}`, `config/schemas/plan.schema.json`
- `src/relayforge/adapters/base.py`, `src/relayforge/adapters/claude/orchestrator.py`
- `src/relayforge/core/{jobs.py,scheduler.py,audit.py,workflows.py,metrics.py,approvals.py}`
- `src/relayforge/api/{schemas.py,app.py,routes/jobs.py,routes/approvals.py,routes/metrics.py}`
- `web/src/{api.ts,App.tsx,pages/Dashboard.tsx,pages/JobDetail.tsx,pages/Metrics.tsx}`
- `tests/{unit/test_workflows.py,integration/test_metrics.py,integration/test_workflow_flows.py,integration/test_jobs_api.py,integration/test_approvals.py}`, `tests/fakes/{fake_agent.py,fake_codex.py}`

## Criterios de aceptación

1. Un diff que toque `auth/**` se eleva a security sin importar workflow solicitado o sugerido; la sugerencia security solicita aprobación antes de implementar.
2. Workflow trivial ejecuta checks configurados y no llama al auditor.
3. Feature/security siguen llamando al auditor; security añade su perfil explícito.
4. `auto` valida la sugerencia y falla de forma cerrada si el valor no está admitido.
5. Métricas de cinco Jobs de prueba coinciden con sus Jobs, pasos, errores, checks y findings; filtros temporales respetan UTC y validación.
6. La interfaz muestra agregados y tratamiento de carga/error/vacío.
7. Antigravity revisa el diff y ejecuta lint, tipos, pruebas, build y `git diff --check`.

## Resultado de implementación y auditoría (2026-10-04)

- Estado: completada; auditoría Antigravity **APROBADO**, run `9bbbc858e37842048a01d071dda4fcf6`, modelo `gemini-3.8-flash-medium`, esfuerzo `medium`; 7/7 criterios y 9/9 comandos, sin acciones denegadas ni cambios del auditor.
- Verificación local y repetida por auditor: Ruff, formato, mypy, pytest completo (105 passed, 1 skipped, 1 warning), ESLint, TypeScript, Vitest (9 archivos/10 pruebas), build web y `git diff --check` PASS.
- El test omitido necesita crear un symlink; Windows devolvió `WinError 1314` por privilegios del proceso. La advertencia restante es deprecación Starlette/httpx en `TestClient`.
- Graphify incremental: 1309 nodos, 2821 relaciones, 125 comunidades; 38 archivos de código reextraídos.
- Corrección durante verificación: `_audit(..., profile="default")` mantiene compatibilidad con invocaciones previas que no pasan un perfil.

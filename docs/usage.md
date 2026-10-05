# Proyectos y trabajos

Guía del checkout de desarrollo. El contenedor observado usa una imagen anterior; la interfaz nueva requiere cerrar gates y recrear el servicio. Estado: desarrollo temprano.

## Preparar el proyecto

Abre **Crear o registrar proyecto**. Para uno existente, proporciona nombre y ruta Git accesible al runtime. Para uno nuevo, selecciona creación bajo `projects_root`: se inicializa el repositorio local y su base inicial. No se crea un remoto GitHub.

Checks: lista JSON con `name`, `argv` y timeout opcional. Se ejecutan en el worktree sin shell. Registra solo repositorios/comandos confiables. Preparar dependencias es un paso distinto; no autoriza instaladores arbitrarios como checks.

En Docker la ruta es interna. Escribir una ruta de la laptop no añade un montaje. Antes de incorporar otro proyecto acuerda archivos, acceso, rama base, checks y tarea inicial; esa integración se propone en Fase 13.

## Crear y seguir la tarea

1. Abre el proyecto, consulta su historial y selecciona **Nueva tarea**.
2. Escribe un objetivo verificable y acotado; usa `feature` para checks/auditoría.
3. Selecciona planner Claude/Codex y modelos válidos de planificación, implementación Codex y auditoría Antigravity. Vacío usa el predeterminado de la CLI.
4. Revisa y aprueba el plan antes de implementar.
5. Consulta fases, diff, resultados y hallazgos. Puedes volver después mientras el host permanezca disponible.

La UI de proyecto envía `require_plan_approval=true`; el API conserva fallback de workflow para clientes que lo omiten. Un identificador válido sintácticamente no prueba disponibilidad del modelo en la cuenta.

## Continuar tras una pausa

Cuota/auth reconocidas dejan `WAITING_AGENT` y conservan etapa/contexto. En planificación/triage puede seleccionarse Codex para continuar. Implementación sigue asignada a Codex; Antigravity permanece auditor. Seleccionar agente no concede permisos nuevos.

Dispatch usa la versión vigente del Job. Etapa activa, versión obsoleta o rol incompatible producen 409; cuerpo/modelo inválidos, 422. Recarga para obtener el estado vigente antes de reintentar.

No se transfieren sesiones de proveedores entre sí. Se conserva Job, plan/eventos y worktree; el proveedor nuevo recibe contexto compatible. Cuotas de cinco horas/semanales figuran desconocidas cuando no hay evidencia. Tokens/turnos muestran lo registrado, no el saldo de toda la cuenta.

## Revisar y entregar

La auditoría puede aprobar, rechazar o bloquear. Rechazo → triage con motivo → brief acotado → revisión, máximo tres iteraciones. Denegación del gate, check faltante o cambios de fuentes no son aprobación aunque la CLI termine con SUCCESS.

Decisiones de entrega tienen scope/snapshot; revisa operación, diff y solapamientos. Cambios posteriores pueden invalidar aprobación. No hay merge automático, force push ni push implícito a rama protegida.

`COMPLETED` puede representar un resultado local sin operación de entrega. Consulta su registro antes de afirmar commit/push. Worktree/branch e historial no demuestran publicación por sí solos.

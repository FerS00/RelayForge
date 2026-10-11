# Proyectos y trabajos

Guía del checkout de desarrollo. Estado: desarrollo temprano; la aceptación del pipeline real desde teléfono sigue pendiente.

## Preparar el proyecto

Abre **Crear o registrar proyecto**. Para uno existente, proporciona nombre y ruta Git accesible al runtime. Para uno nuevo, selecciona creación bajo `projects_root`: se inicializa el repositorio local y su base inicial. No se crea un remoto GitHub.

Checks: lista JSON con `name`, `argv` y timeout opcional. Se ejecutan en el worktree sin shell. Registra solo repositorios/comandos confiables. Preparar dependencias es un paso distinto; no autoriza instaladores arbitrarios como checks.

En Docker la ruta es interna. Escribir una ruta de la laptop no añade un montaje. Antes de incorporar otro proyecto acuerda archivos, acceso, rama base, checks y tarea inicial; esa integración se propone en Fase 13.

## Crear y seguir la tarea

1. Abre el proyecto, consulta su historial y selecciona **Nueva tarea**.
2. Escribe un objetivo verificable y acotado; usa `feature` para checks/auditoría.
3. Selecciona planner Claude/Codex y el modelo de cada etapa en su lista desplegable. **Predeterminado de la CLI** deja el modelo sin sobrescribir; no es obligatorio elegir uno explícito.
4. Revisa y aprueba el plan antes de implementar.
5. Consulta fases, diff, resultados y hallazgos. Puedes volver después mientras el host permanezca disponible.

El catálogo combina los modelos configurados con los identificadores anunciados por las CLIs: caché de modelos de Codex, `agy models` y aliases de `claude --help`. Se actualiza con el probe de estado, con caché de 30 segundos; no demuestra cuota ni acceso efectivo a todos los modelos. Si no hay catálogo, puede usarse el predeterminado. Cambiar el agente limpia la selección; un modelo histórico fuera del catálogo se conserva y se muestra deshabilitado hasta elegir otra opción.

La UI de proyecto envía `require_plan_approval=true`; el API conserva fallback de workflow para clientes que lo omiten. Un identificador válido sintácticamente no prueba disponibilidad del modelo en la cuenta.

## Continuar tras una pausa

Cuota/auth reconocidas dejan `WAITING_AGENT` y conservan etapa/contexto. En planificación/triage puede seleccionarse Codex para continuar. Implementación sigue asignada a Codex; Antigravity permanece auditor. Seleccionar agente no concede permisos nuevos.

Dispatch usa la versión vigente del Job. Etapa activa, versión obsoleta o rol incompatible producen 409; cuerpo/modelo inválidos, 422. Recarga para obtener el estado vigente antes de reintentar.

No se transfieren sesiones de proveedores entre sí. Se conserva Job, plan/eventos y worktree; el proveedor nuevo recibe contexto compatible. Cuotas de cinco horas/semanales figuran desconocidas cuando no hay evidencia. Tokens/turnos muestran lo registrado, no el saldo de toda la cuenta.

## Revisar y entregar

La auditoría puede aprobar, rechazar o bloquear. Rechazo → triage con motivo → brief acotado → revisión, máximo tres iteraciones. Denegación del gate, check faltante o cambios de fuentes no son aprobación aunque la CLI termine con SUCCESS.

Decisiones de entrega tienen scope/snapshot; revisa operación, diff y solapamientos. Cambios posteriores pueden invalidar aprobación. No hay merge automático, force push ni push implícito a rama protegida.

`COMPLETED` puede representar un resultado local sin operación de entrega. Consulta su registro antes de afirmar commit/push. Worktree/branch e historial no demuestran publicación por sí solos.


## Chat y evidencia (CH-02)

La pantalla inicial muestra el compositor. Escribe directamente: la primera solicitud crea un chat con el agente/modelo predeterminado. Agente/modelo son opcionales al crear la conversación; no se exige un título, workflow o proyecto. El encabezado indica agente/modelo y runtime efectivos. Jobs y proyectos siguen accesibles como paneles auxiliares.

Adjuntar acepta TXT, MD, LOG, JSON, CSV, PNG, JPEG, WEBP, PDF y DOCX. Límites: 8 archivos por mensaje, 8 MB por archivo y 32 MB en total. Se puede enviar evidencia sin texto. El servidor valida contenido y pertenencia; documentos se descargan, imágenes validadas se muestran en el historial. Texto extraído se redacta antes de enviarlo. Archivos originales de imágenes/PDF/DOCX se conservan como evidencia del usuario; no hay redacción visual automática. PDF escaneado indica sin texto extraído: no se ejecuta OCR. Límite de extracción64kcaracteres/archivo,256k/turno; PDF100páginas, imágenes20Mpx, DOCX8MBexpandido.

Texto/archivos permanecen en el compositor si falla un envío. Los reintentos de un mismo mensaje conservan su clave idempotente. Historial se carga sin exigir SSE conectado y se refresca mientras hay un turno activo. Una conversación conserva proveedor/sesión; las acciones y el control gráfico se habilitan en fases siguientes, no en CH-02 readonly.

## Acciones desde el chat (CH-03)

Pide una lectura, escritura de texto o tarea local indicando el recurso; para desarrollo usa el nombre de un repositorio registrado. El agente propone acciones estructuradas; ves el objetivo y contenido antes de aprobar. Escribir «listo» no aprueba. La decisión se limita al hash/versión y snapshot actual; un cambio del recurso invalida la aprobación. Rutas de credenciales, symlinks/junctions, UNC, dispositivos/ADS y worktrees activos se rechazan. Las tareas nativas usan Codex workspace-write sin elevación ni bypass. La GUI corresponde a CH04.

Puedes enviar mensajes mientras el agente responde: quedan en una cola persistente. Los resultados de herramientas vuelven al agente y al hilo. Desarrollo crea Jobs internos con plan/checks/auditoría/diff y aprobaciones inline; varios Jobs conservan sesiones separadas dentro del mismo chat. Las aprobaciones de entrega mantienen el alcance exacto existente y no autorizan automáticamente commit/push. Reiniciar marca acciones inciertas interrupted; revisa el recurso y solicita una nueva acción, sin repetir efectos automáticamente.

## Entregables y previews (CH-06)

El panel **Entregables** del chat explora el workspace de la conversación y los worktrees de sus Jobs. Puedes descargar archivos o un ZIP de la carpeta actual. Se excluyen repositorios Git, dependencias, cachés y rutas habituales de credenciales; no se siguen symlinks ni junctions. Las descargas individuales se limitan a 25 MiB; los ZIP a 10 000 archivos y 512 MiB sin comprimir.

El agente puede proponer un preview estático o un servidor local definido por `relayforge-preview.json`. Los comandos requieren aprobación de esa configuración exacta. El servidor corre con los permisos de la cuenta de Windows y no instala dependencias. Revisa el contenido y el manifiesto antes de aprobar. El gateway usa otro origen, emite tickets de un solo uso y no reenvía las cookies de sesión de la consola. El panel puede abrirlo en otra pestaña o dentro de un iframe aislado.

El listener del gateway se limita a loopback. Para abrirlo desde otro dispositivo se requiere configurar el origen HTTPS público y el enrutamiento correspondiente en el entorno del operador; RelayForge no cambia Tailscale Serve. En `container_mode` los previews no están disponibles, aunque el explorador de entregables sigue funcionando.

## Esfuerzo y herramientas por conversación (CH-07)

En una conversación existente, «Esfuerzo y herramientas» permite elegir el nivel de razonamiento y activar o desactivar herramientas. Solo aparecen los niveles que admite el modelo efectivo (catálogo de Codex en `models_cache.json`; Claude admite `low`–`max`); `ultra` nunca se ofrece. Un nivel no admitido devuelve `effort_unsupported`, sin degradarse.

| Herramienta | Acciones | Predeterminado |
|---|---|---|
| Escribir archivos | `write_file` | Activa |
| Comandos locales | `native_task` | Activa |
| Git local y desarrollo | `development_job` | Activa |
| Preview | `start_preview`, `stop_preview` | Activa |
| Búsqueda web | Codex `--search`; Claude sin `WebSearch`/`WebFetch` denegados | Desactivada |
| Entrega remota | Jobs de chat sin `review_only` | Desactivada |

La configuración se copia al turno cuando se envía el mensaje: un cambio nunca altera un turno en curso ni uno ya encolado. El core rechaza una acción de una herramienta desactivada (`tool_disabled:<clave>`) y el agente recibe el rechazo en el mismo hilo. Ningún interruptor sustituye las aprobaciones exactas de acciones, plan o entrega, ni concede commit, push, publicación o elevación. La entrega remota requiere Git local. Cada respuesta muestra el modelo y el esfuerzo efectivos de su turno. API: `PATCH /api/conversations/{id}/settings` con `settings_version` (409 en conflicto).

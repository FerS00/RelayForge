# Verificación y aceptación

Estado de los gates locales automatizados del candidato: **Aprobado con observaciones**. El producto sigue en **desarrollo temprano** y su aceptación operativa permanece pendiente.

Los [resultados originales](evidence/2026-10-05-console-checks.json) preservan el primer rechazo. La [auditoría correctiva](evidence/2026-10-05-console-correction.json) registra la revisión vigente sin logs completos ni credenciales.

## Evidencia actual — 2026-10-05

Auditoría correctiva `e07678935a1f49acb1d867add49bf39d`, Antigravity `gemini-3.8-flash-high`, esfuerzo high: **APROBADO**, 50/50 comandos, cero denegaciones, cero cambios del auditor y cero checks omitidos. El primer audit `56984be1120c4cbd8ff9aeca093c4cf2` fue rechazado; ambos hallazgos quedaron corregidos y la revisión nueva confirmó los gates locales. La ejecución intermedia `5457f9fa71fa4b86be582a29ec77c0a7` no cuenta como aprobación: su gate registró `manage_task` denegado.

| Comprobación | Resultado | Límite |
|---|---|---|
| `git diff --check` | Aprobado | Avisos LF/CRLF; no hay commit nuevo. |
| `uv run ruff check src tests` | Aprobado | El I001 de `tests/integration/test_doctor.py` fue corregido. |
| `uv run ruff format --check src tests` | Aprobado | 125 archivos en la revisión actual. |
| `uv run mypy src` | Aprobado | 79 fuentes en la revisión actual. |
| `uv run pytest -q` | Aprobado con observaciones | Revisión actual: 143 passed/1 skipped por WinError 1314 de symlink; aviso deprecado Starlette/httpx. El auditor anterior ejecutó 139 passed/1 skipped. |
| `npm --prefix web run lint` | Aprobado | ESLint. |
| `npm --prefix web run typecheck` | Aprobado | TypeScript. |
| `npm --prefix web run test` | Aprobado | Revisión actual: 13 archivos/20 pruebas Vitest. |
| `npm --prefix web run build` | Aprobado | Build Vite. |
| `uv run pytest -q tests/integration/test_auth.py tests/integration/test_db_migrations.py tests/integration/test_jobs_api.py` | Aprobado | 21 passed; warning deprecado Starlette/httpx. |
| Navegador móvil emulado | Aprobado con observaciones | Backend aislado y fakes; no prueba móvil físico ni cuentas reales. |
| Docker Windows, contenedor actual | Aprobado con observaciones | Engine 29.8.2; imagen `sha256:ac851022…`, cinco volúmenes, estado healthy, migración `0008_agent_dispatch`; Retención exacta de un proyecto, dos Jobs, cuatro steps, 26 eventos y una aprobación comprobada por conteos/hashes antes/después de recreate. |
| CLI y auth dentro del contenedor | Aprobado con observaciones | Versiones Claude 2.1.288, Codex 0.159.2 y AGY 1.2.16 disponibles. Después del recreate actual solo Codex conserva auth disponible; Claude y AGY requieren login nuevamente. |
| HTTPS tailnet y pairing inválido | Aprobado con observaciones | HTTP 200 y código inválido rechazado con 403 desde navegador de la laptop, viewport 390×844; no equivale a prueba desde otro dispositivo. Consola también registra `/favicon.ico` 404 (Leve, Informativo). |
| Teléfono físico, navegador manual Tailscale | Aprobado con observaciones | El propietario registró el proyecto, creó JOB-000002, aprobó el plan y cerró el navegador durante IMPLEMENTING. Implementación real completada; check falló y auditoría del Job no se ejecutó. No se requiere ADB/Appium para esta prueba. |
| CI GitHub para esta revisión | No ejecutado | La auditoría local no equivale a CI remota. |

En navegador se comprobó crear proyecto, seleccionar modelos, crear Job Claude, fallo simulado de cuota, relevo Codex, aprobación humana antes de implementar, archivo/diff sintéticos y resultado local. Historial persistió tras recarga y reinicio del servidor de prueba. Vistas revisadas en 360 px no mostraron desbordamiento; validación HTML de modelo acepta formato permitido y rechaza caracteres inválidos. Se corrigieron previamente el pattern HTML y un timeout de probe Windows que podía esperar pipes heredados.

## Hallazgos abiertos

| Severidad | Categoría | Evidencia/impacto | Cierre sugerido |
|---|---|---|---|
| Informativo | Cobertura Windows | Prueba de symlink omitida por WinError 1314 | Ejecutarla en un entorno con privilegio de symlink; no elevar silenciosamente. |
| Alto | Aceptación operativa | No hay Job completo validado con pipeline real desde teléfono; la retención de Jobs/proyectos ya se comprobó; AGY requiere recuperar su login | Ejecutar la tarea desechable desde un teléfono disponible tras recuperar auth de AGY; Fase 12. |
| Medio | Recuperación | Reinicio físico con Job activo/cancelación real siguen pendientes | Matriz de PID/creación, estados y eventos; Fase 14. |

## Ejecución automatizada y pruebas reales

La política de tests exige fakes o dry-run, sin cuentas/CLIs reales. Los probes de login/versiones del servicio se ejecutan por separado. El test de fingerprint usa un doble sintético para `_agent`; el login y la ejecución real de proveedores se validan por separado.

El propietario autorizó validación manual desde el navegador del teléfono sobre Tailscale, sin ADB/Appium. Registró el repo desechable y aprobó el plan de JOB-000002; reportó IMPLEMENTING y cierre del navegador. La ejecución continuó hasta completar la implementación real de README.md, sin commit ni acciones remotas. JOB-000001 falló al usar planner Claude; JOB-000002 usó Codex y falló posteriormente en el check (`checks_failed`, exit 129). La auditoría real del Job no se ejecutó y la aceptación completa sigue pendiente.

Se autorizó y creó únicamente el commit semilla del repo desechable; se añadieron a `safe.directory` solo el repo base y el worktree JOB-000002. Se actualizó únicamente el check del proyecto de prueba a `git diff --check`. Reproducción dentro del contenedor: el entorno filtrado del check fallaba; añadir `USERPROFILE` permitió a Git encontrar la configuración autorizada y devolvió exit 0. La corrección conserva la exclusión de credenciales.

El cambio de selector usa un select nativo opcional y catálogos de las CLIs. Verificación del cambio: Ruff, formato (125 archivos), mypy (79 fuentes), 14 pruebas Python aprobadas/1 omitida por symlink, 4 pruebas web aprobadas, lint/typecheck/build web aprobados. Navegador de laptop a 390×844 con API sintética: selección, reset por agente y formulario válido, sin desbordamiento. Antigravity aprobó la revisión independiente `a1d9a329ddfc4c36a7aa417b98cbe988`, gemini-3.8-flash-high/high, nueve checks sin denegaciones ni cambios; el primer intento agotó tiempo antes del dictamen y no cuenta como aprobación. Suites completas posteriores: 143 Python aprobadas/una omitida y 20 web aprobadas. Esta evidencia no sustituye la revisión del selector desde el teléfono ni la auditoría real del Job.

Recreate completado con retención exacta y check real exit0. HTTP local y HTTPS tailnet 200 desde laptop; contenedor healthy con imagen ac851022. Pendientes: restaurar auth de Claude/AGY tras recreate; selector desplegado revisado en teléfono; pipeline real completo con diff/checks/auditoría; identidad no permitida desde otro dispositivo. Cancelación/reinicio físico y backup/restauración pertenecen a Fase 14. CI remota de Fase 11 está comprobada en `ce26d7b`; no se ejecutó CI remota para los cambios actuales.

Las suites y comandos de [CONTRIBUTING](../CONTRIBUTING.md) son verificaciones obligatorias de cambios futuros. No presentar el veredicto textual de la CLI como aprobación si el gate registra denegaciones o faltan checks. Cada fase nueva tiene sus criterios en el [plan](PLAN_PROYECTO.md).


## Evidencia CH-02

Pruebas backend de adjuntos: validación real PNG/PDF/DOCX/texto, redacción, zip expandido, pertenencia, consumo único, idempotencia y bloqueo de integridad alterada. Pruebas web nuevas: inicio=compositor, primer mensaje crea chat, borrador/archivos preservados por error, adjuntos sin texto e IME.

Navegador real con backend local y proveedor doble: POSTmensaje202 con LOG/PNG, respuestaEvidenciarecibida, previewimagen, historial tras reload, viewport390×844 sin overflow. Menú móvil se cierra al crear conversación. Console0errors/0warnings tras pairing. Es identidad/prueba local sintética; no sustituye al teléfono Tailscale.

Proveedor real Windows: Codexgpt-6-luna/medium recibió evidence.txt=FAROCH02 y PNG azul, respondió «FAROCH02, azul.», workspace0archivos. Es evidencia de entrega al agente real, distinta de Vitest/Playwright con dobles. Antigravity 030898a4716049558f9edc26e1c53215: APROBADO, nueve checks, 166 Python/24 web aprobados, un symlink omitido, cero denegaciones/cambios/omisiones. Corrección ciclo1: normalización LF de Dockerfile.windows; contenido conservado.

## Evidencia CH-03 (candidato, auditoría pendiente)

Última suite completa: 182 Python aprobadas/1symlink omitido; pruebas adicionales de migración preservaron exactamente steps/events/artifacts/findings/approvals/grants y rechazaron downgrade con Jobs compartidos. Ruff/mypy92fuentes; 26 web aprobadas antes de añadir regresión de Content-Type. RealCodexgpt-6-luna/medium propuso write_file, esperó aprobación y creó solamente note.txt=FAROCH03; respuesta posterior confirmó8bytes. Probe temporal relayforge-ch03-cfc025dead7c4a69bd80afad33f0c5e5.

Browserreal con agente/auditor ficticios: write_file aprobado desde UI; desarrollo natural sin formulario, plan aprobado inline; implementación/checks/auditoría ficticia SUCCEEDED. Entrega WAITING_APPROVAL conservada, no commit/push aprobado. Recarga y móvil390×844 se verifican separadamente; no es teléfono físico ni auditor real de ese Job. Primer intento de UI reveló Content-Type faltante; corregido y test agregado.

### Límite de la evidencia al traspaso, 2026-10-06

Tras la suite de 182 pruebas se añadieron review_only, retorno de resultados terminales y ajustes de recuperación. Pasaron un subconjunto de 17 pruebas y la prueba posterior de Job con origin sin cambio de HEAD ni entrega remota. Últimos Ruff/formato: 144 archivos; mypy: 92 fuentes. Última web: 27 pruebas en 14 suites, lint/typecheck/build aprobados. Native_task real con Codex ejecutó PowerShell, respondió 8 y no cambió archivos.

Suite completa posterior, navegador final review_only y auditoría independiente CH-03: **No ejecutado**. Los servidores QA de los puertos 8876/8887 no escuchan al cierre. Reiniciar con un DataDir nuevo: las DB de probes intermedios no representan la migración 0011 final. No se ejecutaron pruebas adicionales durante el traspaso.

## CH-06

Las pruebas de previews usan `tests/fakes/fake_preview_server.py`, un servidor HTTP de la biblioteca estándar; no ejecutan CLIs reales de agentes ni acceden a red externa. Las pruebas de gateway verifican tickets, aislamiento de cookies y cabeceras. `tests/unit/test_deliverables.py` cubre exclusiones, traversal y enlaces; la comprobación de junction requiere Windows y puede depender de los permisos disponibles. La aceptación móvil requiere navegador real a 390×844. La apertura por HTTPS desde un teléfono y cualquier cambio de Tailscale Serve quedan fuera de las pruebas automatizadas.

## CH-07 y CH-04

`tests/unit/test_conversation_settings.py` cubre política predeterminada, dependencias, catálogo de esfuerzos (sin `ultra`) y argv de Codex/Claude; `tests/integration/test_conversation_settings_flow.py` cubre PATCH con versión/CSRF, aplicación desde el turno siguiente, rechazo en core de herramientas desactivadas y `review_only` según entrega remota; `test_db_migrations.py` cubre ida y vuelta de 0013 y la tabla de 0014. El worker GUI se verificó manualmente con `probe` (sesión interactiva) y con `launch`/`inspect` desde una sesión elevada, que devolvió `target_elevated` como exige la especificación; la operación completa requiere un runtime sin elevación y la conexión al agente pendiente de autorización.

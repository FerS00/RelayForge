# Operación y recuperación

RelayForge se inicia manualmente en la sesión del usuario. No instala autorun ni una tarea programada. El servicio no continúa cuando la laptop está apagada.

## Runtime nativo

Abre PowerShell normal, sin elevación, desde el repositorio. Usa un workspace existente y un DataDir persistente; conserva los mismos valores de `RELAYFORGE_HOME` y `RELAYFORGE_WORKSPACE_DIR` para pairing y reinicios:

```powershell
./scripts/Start-Native.ps1 -WorkspaceDir C:/ruta/de/trabajo -DataDir C:/ruta/RelayForge-data -Port 8876 -AllowedHosts <host>.ts.net -AllowedLogins <login-tailscale> -PreviewPublicOrigin https://<host>.ts.net:8443
```

El script inicia `uv run relayforge serve` en primer plano. Para detenerlo, usa `Ctrl+C`. Para volver a iniciarlo, ejecuta de nuevo el script con el mismo DataDir y workspace. No apuntes `-DataDir` a una carpeta que contenga una base que no quieras usar; el script rechaza un `relayforge.db` preexistente al preparar el directorio. Pairing se realiza desde esa instancia y queda asociado a su `RELAYFORGE_HOME`.

## Tailscale Serve

La entrada principal del runtime nativo es `/` hacia `127.0.0.1:8876`; el origen de previews usa `8443` hacia `127.0.0.1:8793`. Estos comandos cambian la configuración de Serve del host y deben ejecutarlos manualmente:

```powershell
tailscale serve --bg http://127.0.0.1:8876
tailscale serve --bg --https=8443 http://127.0.0.1:8793
tailscale serve status
```

Para retirar la entrada de previews:

```powershell
tailscale serve --https=8443 off
```

Para revertir `/`, restaura manualmente el destino anterior que muestre `tailscale serve status`; no uses `tailscale serve reset` si necesitas conservar otras entradas.

## Docker Windows alternativo

El runtime nativo es el modo principal. Para operar el contenedor Windows, selecciona el contexto explícitamente y conserva los volúmenes:

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml ps
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml logs --tail 100 relayforge
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml stop
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml up -d
```

No uses `down -v`. El backup en caliente se ejecuta dentro del contenedor para que `sqlite3.Connection.backup` lea la base y WAL desde el mismo volumen:

```powershell
docker --context desktop-windows compose --env-file .env.docker -f compose.windows.yaml exec relayforge relayforge.exe backup --output C:/relayforge-home/backups
```

La restauración de Docker debe dirigirse a un `home` nuevo y vacío. No montes ni uses el home activo como destino.

## Backup y restauración

En runtime nativo, `RELAYFORGE_HOME` selecciona el home. El destino predeterminado es `<home>/backups`; `--output` permite elegir otro directorio, siempre fuera de `<home>/data`:

```powershell
uv run relayforge backup
uv run relayforge backup --output C:/ruta/segura/RelayForge-backups
```

El comando crea un directorio con marca UTC, copia la base mediante la API SQLite de backup, conserva los archivos regulares de `data/attachments` y escribe `manifest.json` con la revisión, los conteos y hashes SHA-256. Omite enlaces y reparse points. No respalda configuración, credenciales, worktrees, `desktop-files` ni logs de procesos bajo `data/chat`, `data/jobs`, `data/previews` y `data/desktop`.

Restaura solo en una carpeta nueva o vacía. El comando no carga settings del runtime ni requiere un workspace configurado para el destino:

```powershell
uv run relayforge restore --from C:/ruta/segura/RelayForge-backups/relayforge-backup-20261010T120000Z --home C:/ruta/nueva/RelayForge-data
```

La restauración valida el formato y hashes antes de escribir. Rechaza un destino no vacío; nunca sobrescribe `relayforge.db`. Luego ejecuta migraciones y compara los conteos restaurados con el manifiesto. Un error se imprime como JSON `{"error":"<código>"}` y devuelve código de salida 2.

Antes de actualizar RelayForge, crea un backup manual y confirma que el comando terminó con código 0. La retención es manual: elimina los backups antiguos desde el Explorador después de decidir cuánto historial conservar. Mantén al menos una copia fuera del DataDir si necesitas protegerte frente al fallo del disco.

## Matriz de recuperación Fase 14

| Criterio | Evidencia automatizable | Evidencia que sigue siendo manual |
|---|---|---|
| 14.1 Historia tras finalizar y reiniciar backend; procesos activos marcados interrumpidos | `tests/integration/test_job_reconcile.py::test_startup_reconciliation_interrupts_active_jobs` y `tests/integration/test_chat_flow.py::test_chat_persists_turn_and_replays_idempotency` | Confirmar en la instancia del propietario después de parar y volver a iniciar el runtime nativo |
| 14.2 Reinicio físico con Job activo no deja un Job activo sin proceso | `test_job_reconcile.py` cubre la reconciliación de arranque, no un ciclo de energía | Reinicio físico de la laptop con un Job activo y comprobación posterior de su estado |
| 14.3 Cancelación termina descendientes identificados | `tests/integration/test_jobs_api.py::test_cancel_active_plan_kills_fake_process`, `tests/integration/test_checks_workflow.py::test_check_timeout_kills_child_process` y `tests/unit/test_supervisor.py::test_kill_all_is_idempotent` | Verificación adicional en el runtime del propietario si los procesos reales difieren de los dobles |
| 14.4 Resume/retry no duplican pasos ni entrega | `tests/integration/test_reliability_flow.py::test_resume_endpoint_only_requeues_interrupted_job`, `test_transient_failure_waits_for_persisted_retry_time` y `tests/unit/test_jobs.py::test_idempotency_returns_existing_job_without_duplicate_rows` | No requiere interacción física para la cobertura automatizada |
| 14.5 Cuota espera decisión y los errores de red reintentan de forma limitada | `tests/integration/test_reliability_flow.py`, `tests/integration/test_agent_dispatch.py` y `tests/unit/test_reliability.py` usan fallos controlados | La respuesta real de cada proveedor no se simula con una CLI real en pytest |
| 14.6 Backup/restauración preserva trazabilidad | `tests/unit/test_backup.py` y `tests/integration/test_backup_restore.py`: WAL, integridad, conteos y hashes de adjuntos en homes temporales | Ejecutar un backup y restauración controlados en una ubicación nueva del propietario antes de depender de la copia |
| 14.7 Dos Jobs del mismo repo usan worktrees distintos y muestran solapamientos | `tests/integration/test_implementation_workflow.py::test_two_jobs_on_one_repo_run_in_distinct_worktrees` | Validar el flujo visual desde el teléfono si se requiere aceptación de interfaz |
| 14.8 `doctor` refleja disponibilidad tras arrancar | `tests/integration/test_doctor.py::test_doctor_endpoint_reports_check_names_without_command_output` | Ejecutar `uv run relayforge doctor` en la instancia nativa después del arranque |

Las pruebas automatizadas usan directorios temporales y dobles; no prueban un reinicio físico, un proveedor autenticado ni la disponibilidad con la laptop apagada. La aceptación operativa de recuperación física requiere que el propietario reinicie la laptop y revise el estado del backend y Jobs.

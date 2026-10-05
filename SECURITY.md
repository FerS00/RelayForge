# Seguridad

RelayForge está en desarrollo temprano y requiere un host Windows de confianza. En ejecución nativa enlaza `127.0.0.1`; en Docker Windows enlaza `0.0.0.0` dentro de NAT, sin puertos Docker publicados y con gateway proxy exacto. Un portproxy escucha solo loopback en el host y Tailscale Serve reenvía allí. Acceso remoto requiere pairing, allowlist exacta y Host/Origin/CSRF; no habilites bind público/LAN en el host ni Funnel.

Los agentes y los checks ejecutan procesos con la cuenta actual. Los checks declarados para un repositorio pueden acceder a la red y a los permisos de esa cuenta. Registra repositorios en los que confías. El límite S0 documentado permite que Codex lea archivos accesibles al usuario; el aislamiento de worktree no es un sandbox del sistema operativo.

RelayForge redacta patrones comunes de secretos y rutas personales antes de guardar o emitir texto de agentes y antes de cerrar logs de proceso. Esta defensa no detecta todos los secretos ni reemplaza la protección de credenciales en el repositorio. No uses contenido confidencial en pruebas y no incluyas `.env`, claves o tokens en issues, logs o reportes públicos.

## Reportar vulnerabilidades

No publiques detalles explotables ni datos sensibles en un issue público. Usa la función de reporte privado de vulnerabilidades de GitHub para este repositorio si está habilitada. Si no está disponible, contacta al mantenedor por un canal privado antes de publicar los detalles. Incluye versión o commit, impacto, pasos mínimos de reproducción y una corrección propuesta si la tienes.

## Estado de soporte

No hay versión estable ni compromiso de soporte. Los gates locales de Python y web tienen auditoría independiente aprobada. El runtime Docker Windows, los trabajos con proveedores reales, la comprobación en teléfono físico y la recuperación tras reinicio siguen pendientes. Consulta [testing](docs/testing.md) y [plan](docs/PLAN_PROYECTO.md). Una aprobación textual no prevalece sobre una denegación del gate o un check omitido.
